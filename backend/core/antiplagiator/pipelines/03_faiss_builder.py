"""
03_faiss_builder.py — FAISS index builder (v3, memmap + streaming).

Fixes for CUDA OOM on 15M+ vector corpus:

  FIX 1 — encode_to_memmap (v2)
     Each encode batch is written to disk immediately and freed from GPU.
     GPU never holds more than one batch (~400 MB) at a time.

  FIX 2 — streaming JSONL read (v3)
     build_and_save no longer loads all texts into a Python list first.
     Previously: texts = [r["text"] for r in records]  <- 20-30 GB RAM for 15M chunks
     Now: texts are read from the JSONL file in streaming batches during encoding.
     RAM usage for text strings stays flat regardless of corpus size.

  FIX 3 — two-pass JSONL read
     Pass 1: read metadata only (no text) — fast, low memory
     Pass 2: read text in streaming batches during encoding

Usage (Colab A100):
  python 03_faiss_builder.py \\
      --input chunked_database.jsonl \\
      --artifacts-dir artifacts/ \\
      --device cuda \\
      --index-type pq \\
      --nlist 4096 \\
      --nprobe 64
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

LOGGER = logging.getLogger("faiss_builder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

MODEL_NAME   = "BAAI/bge-m3"
NLIST        = 4096
NPROBE       = 64
ENCODE_BATCH = 512    # texts per GPU forward pass
CHUNK_BATCH  = 50_000 # texts per encoding iteration (written to memmap then freed)

PQ_M     = 64
PQ_NBITS = 8


# ---------------------------------------------------------------------------
# Index factories
# ---------------------------------------------------------------------------

def build_ivfflat_index(dimension: int, nlist: int) -> faiss.IndexIVFFlat:
    quantizer = faiss.IndexFlatIP(dimension)
    index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
    index.nprobe = NPROBE
    return index


def build_ivfpq_index(dimension: int, nlist: int, m: int, nbits: int) -> faiss.IndexIVFPQ:
    if dimension % m != 0:
        valid = [x for x in [8, 16, 32, 64, 128, 256] if dimension % x == 0]
        raise ValueError(
            f"PQ sub-quantizers m={m} must divide dimension={dimension} evenly. "
            f"Valid values: {valid}"
        )
    quantizer = faiss.IndexFlatIP(dimension)
    index = faiss.IndexIVFPQ(quantizer, dimension, nlist, m, nbits)
    index.nprobe = NPROBE
    return index


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def encode_batch(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    with torch.no_grad():
        embeddings = model.encode(
            texts,
            batch_size=ENCODE_BATCH,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return embeddings.astype("float32")


def stream_encode_to_memmap(
    model: SentenceTransformer,
    input_path: Path,
    dimension: int,
    memmap_path: Path,
    label: str,
    total_chunks: int,
) -> np.ndarray:
    """
    Stream texts from JSONL, encode in batches, write directly to memmap.

    Never loads more than CHUNK_BATCH text strings into RAM at once.
    GPU never holds more than one batch of embeddings at a time.

    Memory profile (15M vectors):
      - Text strings in RAM:  CHUNK_BATCH x ~100 words x ~6 bytes = ~30 MB
      - GPU (embeddings):     ENCODE_BATCH x 1024 x 4 bytes = ~2 MB
      - Memmap on disk:       15M x 1024 x 4 bytes = ~60 GB
    """
    LOGGER.info(
        "[%s] Pre-allocating memmap: %d vectors x %d dims = %.1f GB on disk",
        label, total_chunks, dimension, total_chunks * dimension * 4 / 1024**3,
    )

    embeddings = np.memmap(
        str(memmap_path),
        dtype="float32",
        mode="w+",
        shape=(total_chunks, dimension),
    )

    write_pos = 0
    batch_texts: list[str] = []

    def flush_batch():
        nonlocal write_pos
        if not batch_texts:
            return
        batch_emb = encode_batch(model, batch_texts)
        end = write_pos + len(batch_texts)
        embeddings[write_pos:end] = batch_emb
        embeddings.flush()
        del batch_emb
        write_pos += len(batch_texts)
        batch_texts.clear()

    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            text = json.loads(line).get("text", "")
            batch_texts.append(text)

            if len(batch_texts) >= CHUNK_BATCH:
                flush_batch()
                LOGGER.info("[%s] Encoded + saved %d / %d", label, write_pos, total_chunks)

    flush_batch()  # flush remaining
    LOGGER.info("[%s] All %d vectors encoded and on disk.", label, write_pos)
    return embeddings


# ---------------------------------------------------------------------------
# Two-pass JSONL helpers
# ---------------------------------------------------------------------------

def count_and_read_metadata(input_path: Path) -> tuple[int, list[dict], dict[str, list[int]]]:
    """
    Pass 1: read the JSONL once to get:
      - total chunk count
      - metadata list (no text field — keeps RAM low)
      - category -> list of line indices mapping (for per-category indexes)
    """
    metadata: list[dict] = []
    cat_to_indices: dict[str, list[int]] = defaultdict(list)

    LOGGER.info("Pass 1 — reading metadata from %s ...", input_path)
    with input_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            data = json.loads(line)
            meta = {
                "arxiv_id":     data.get("arxiv_id", ""),
                "title":        data.get("title", ""),
                "chunk_id":     data.get("chunk_id", 0),
                "source_type":  data.get("source_type", "unknown"),
                "top_category": data.get("top_category", "unknown"),
            }
            metadata.append(meta)
            cat_to_indices[meta["top_category"]].append(len(metadata) - 1)

    total = len(metadata)
    LOGGER.info("Pass 1 done — %d chunks across %d categories", total, len(cat_to_indices))
    return total, metadata, cat_to_indices


def read_texts_for_indices(input_path: Path, indices: set[int]) -> list[str]:
    """
    Read text fields only for the given line indices.
    Used for per-category index building.
    """
    texts: list[str] = []
    with input_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i in indices and line.strip():
                texts.append(json.loads(line).get("text", ""))
    return texts


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------

def build_index_from_memmap(
    embeddings: np.ndarray,
    n: int,
    nlist: int,
    index_type: str,
    pq_m: int,
    pq_nbits: int,
    dimension: int,
    label: str,
) -> faiss.Index:
    """Train and populate a FAISS index from a memmap array."""
    min_vectors = 39 * nlist
    nlist_actual = nlist
    if n < min_vectors:
        nlist_actual = max(1, n // 39)
        LOGGER.warning(
            "[%s] nlist reduced %d -> %d (need %d vectors, have %d)",
            label, nlist, nlist_actual, min_vectors, n,
        )

    if index_type == "pq":
        LOGGER.info("[%s] Building IVFPQ (nlist=%d, m=%d, nbits=%d) ...",
                    label, nlist_actual, pq_m, pq_nbits)
        index = build_ivfpq_index(dimension, nlist_actual, pq_m, pq_nbits)
    else:
        LOGGER.info("[%s] Building IVFFlat (nlist=%d) ...", label, nlist_actual)
        index = build_ivfflat_index(dimension, nlist_actual)

    LOGGER.info("[%s] Training on %d vectors ...", label, n)
    index.train(embeddings)
    index.add(embeddings)
    return index


def save_index(
    index: faiss.Index,
    metadata: list[dict],
    index_path: Path,
    metadata_path: Path,
    label: str,
) -> None:
    faiss.write_index(index, str(index_path))
    with metadata_path.open("wb") as f:
        pickle.dump(metadata, f)
    size_mb = index_path.stat().st_size / 1024**2
    LOGGER.info("[%s] Saved — %d vectors | %.1f MB", label, index.ntotal, size_mb)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build FAISS indexes — streaming memmap, no GPU OOM"
    )
    parser.add_argument(
        "--input", type=Path,
        default=Path("backend/core/antiplagiator/data/processed/chunked_database.jsonl"),
    )
    parser.add_argument(
        "--artifacts-dir", type=Path,
        default=Path("backend/core/antiplagiator/artifacts"),
    )
    parser.add_argument("--nlist",  type=int, default=NLIST)
    parser.add_argument("--nprobe", type=int, default=NPROBE)
    parser.add_argument("--device", type=str, default="cuda", choices=["cuda", "cpu"])
    parser.add_argument(
        "--index-type", type=str, default="pq", choices=["flat", "pq"],
        help="pq = IVFPQ compressed (~1 GB). flat = IVFFlat full precision (large).",
    )
    parser.add_argument("--pq-m",     type=int, default=PQ_M)
    parser.add_argument("--pq-nbits", type=int, default=PQ_NBITS)
    parser.add_argument(
        "--no-per-category", action="store_true",
        help="Skip per-category index builds.",
    )
    args = parser.parse_args()

    args.artifacts_dir.mkdir(parents=True, exist_ok=True)

    device = args.device if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        gpu = torch.cuda.get_device_properties(0)
        LOGGER.info("GPU: %s (%.1f GB VRAM)", gpu.name, gpu.total_memory / 1024**3)

    LOGGER.info("Loading %s on %s ...", MODEL_NAME, device)
    model = SentenceTransformer(
        MODEL_NAME,
        device=device,
        model_kwargs={"dtype": torch.float16} if device == "cuda" else {},
    )
    # Handle both old and new sentence-transformers API
    try:
        dimension = model.get_embedding_dimension()
    except AttributeError:
        dimension = model.get_sentence_embedding_dimension()
    LOGGER.info("Embedding dimension: %d", dimension)

    if args.index_type == "pq" and dimension % args.pq_m != 0:
        valid = [x for x in [8, 16, 32, 64, 128, 256] if dimension % x == 0]
        parser.error(f"--pq-m {args.pq_m} must divide dimension {dimension}. Valid: {valid}")

    # ── Pass 1: read metadata, count chunks, map categories ──────────────────
    total_chunks, all_metadata, cat_to_indices = count_and_read_metadata(args.input)

    # ── Pass 2: stream encode → memmap ────────────────────────────────────────
    index_path    = args.artifacts_dir / "faiss_document_index.bin"
    metadata_path = args.artifacts_dir / "faiss_metadata.pkl"
    memmap_path   = args.artifacts_dir / "global.memmap.npy"

    embeddings = stream_encode_to_memmap(
        model, args.input, dimension, memmap_path, "GLOBAL", total_chunks
    )

    # ── Build + save global index ─────────────────────────────────────────────
    index = build_index_from_memmap(
        embeddings, total_chunks, args.nlist,
        args.index_type, args.pq_m, args.pq_nbits, dimension, "GLOBAL",
    )
    save_index(index, all_metadata, index_path, metadata_path, "GLOBAL")

    # Free global memmap
    del embeddings, index
    try:
        memmap_path.unlink(missing_ok=True)
        LOGGER.info("Removed global memmap file.")
    except Exception:
        pass

    # ── Build per-category indexes ────────────────────────────────────────────
    if not args.no_per_category:
        cat_dir = args.artifacts_dir / "category_indexes"
        cat_dir.mkdir(exist_ok=True)

        for cat, indices in sorted(cat_to_indices.items()):
            safe = cat.replace("/", "_").replace(".", "_").replace("-", "_")
            cat_index_path = cat_dir / f"faiss_{safe}.bin"
            cat_meta_path  = cat_dir / f"faiss_{safe}_meta.pkl"
            cat_memmap     = cat_dir / f"{safe}.memmap.npy"

            cat_metadata = [all_metadata[i] for i in indices]
            n_cat        = len(indices)

            LOGGER.info("[%s] %d chunks — building per-category index ...", cat, n_cat)

            # Read only this category's texts (one pass through the file)
            indices_set = set(indices)
            cat_texts   = read_texts_for_indices(args.input, indices_set)

            # Encode to per-category memmap
            cat_emb = np.memmap(
                str(cat_memmap), dtype="float32", mode="w+", shape=(n_cat, dimension)
            )
            pos = 0
            for start in range(0, n_cat, CHUNK_BATCH):
                batch = cat_texts[start: start + CHUNK_BATCH]
                emb   = encode_batch(model, batch)
                cat_emb[pos: pos + len(batch)] = emb
                cat_emb.flush()
                del emb
                pos += len(batch)
            del cat_texts

            # Build IVFFlat for per-category (already small)
            cat_index = build_index_from_memmap(
                cat_emb, n_cat, args.nlist,
                "flat", args.pq_m, args.pq_nbits, dimension, cat,
            )
            save_index(cat_index, cat_metadata, cat_index_path, cat_meta_path, cat)

            del cat_emb, cat_index
            try:
                cat_memmap.unlink(missing_ok=True)
            except Exception:
                pass

    LOGGER.info("All indexes built successfully.")


if __name__ == "__main__":
    main()