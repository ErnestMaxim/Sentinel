from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import pickle
import shutil
import time
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

LOGGER = logging.getLogger("faiss_builder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

MODEL_NAME   = "BAAI/bge-base-en-v1.5"
NLIST        = 1024   # good balance: fast training, good recall
NPROBE       = 64
ENCODE_BATCH = 512
CHUNK_BATCH  = 50_000

PQ_M     = 192   # 768/192 = 4 dims/subvector — much better than old M=64
PQ_NBITS = 8

# Checkpoint file — tracks how many vectors have been encoded so far
# Allows resuming encoding after a Colab disconnect
ENCODE_CHECKPOINT_FILE = "encode_checkpoint.json"


# ---------------------------------------------------------------------------
# Disk / memory checks
# ---------------------------------------------------------------------------

def check_disk_space(artifacts_dir: Path, total_chunks: int, dimension: int, index_type: str) -> None:
    """Warn if disk space is insufficient before starting."""
    memmap_gb  = total_chunks * dimension * 4 / 1024**3
    index_gb   = memmap_gb if index_type == "flat" else memmap_gb * 0.05  # PQ ~5% of flat
    needed_gb  = memmap_gb + index_gb + 1  # +1 GB buffer

    free_bytes = shutil.disk_usage(str(artifacts_dir)).free
    free_gb    = free_bytes / 1024**3

    LOGGER.info(
        "Disk check: memmap=%.1f GB | index=%.1f GB | needed=%.1f GB | free=%.1f GB",
        memmap_gb, index_gb, needed_gb, free_gb,
    )
    if free_gb < needed_gb:
        raise RuntimeError(
            f"Insufficient disk space: need {needed_gb:.1f} GB but only {free_gb:.1f} GB free. "
            f"Use --local-scratch-dir /local-scratch if available (368 GB free on Colab A100)."
        )
    LOGGER.info("Disk space OK.")


def log_gpu_memory(label: str = "") -> None:
    if torch.cuda.is_available():
        alloc = torch.cuda.memory_allocated() / 1024**2
        total = torch.cuda.get_device_properties(0).total_memory / 1024**2
        LOGGER.info("GPU memory %s: %.0f / %.0f MB allocated", label, alloc, total)


# ---------------------------------------------------------------------------
# Index factories
# ---------------------------------------------------------------------------

def build_ivfflat_index(dimension: int, nlist: int) -> faiss.IndexIVFFlat:
    """
    IVFFlat — exact inner product, no compression.
    reconstruct_batch works perfectly → reranking gives true cosine scores.
    Score for identical document: ~0.95-0.99
    File size: ~39 GB for 12.7M x 768-dim vectors.
    """
    quantizer = faiss.IndexFlatIP(dimension)
    index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
    index.nprobe = NPROBE
    index.make_direct_map()  # required for reconstruct_batch
    return index


def build_ivfpq_index(dimension: int, nlist: int, m: int, nbits: int) -> faiss.IndexIVFPQ:
    """
    IVFPQ — compressed. ~2 GB for 12.7M x 768-dim vectors.
    reconstruct returns PQ-approximated vectors (not exact originals).
    Score for identical document: ~0.25-0.35 — use threshold 0.20 with this.
    Only use when disk space < 40 GB.
    """
    if dimension % m != 0:
        valid = [x for x in [8, 16, 32, 64, 96, 128, 192, 256] if dimension % x == 0]
        raise ValueError(
            f"PQ sub-quantizers m={m} must divide dimension={dimension} evenly. "
            f"Valid values: {valid}"
        )
    quantizer = faiss.IndexFlatIP(dimension)
    index = faiss.IndexIVFPQ(quantizer, dimension, nlist, m, nbits)
    index.nprobe = NPROBE
    index.make_direct_map()  # enables reconstruct (returns PQ approximation)
    return index


def move_index_to_gpu(index: faiss.Index) -> faiss.Index:
    """Move index to GPU for faster training and add. Falls back to CPU silently."""
    try:
        res = faiss.StandardGpuResources()
        res.setTempMemory(512 * 1024 * 1024)  # 512 MB temp memory
        gpu_index = faiss.index_cpu_to_gpu(res, 0, index)
        LOGGER.info("Index moved to GPU for training/adding.")
        return gpu_index
    except Exception as e:
        LOGGER.warning("Could not move index to GPU (%s) — using CPU.", e)
        return index


# ---------------------------------------------------------------------------
# Encoding — with resumable checkpoint
# ---------------------------------------------------------------------------

def encode_batch_texts(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
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


def _load_encode_checkpoint(checkpoint_path: Path) -> int:
    """Return the number of vectors already encoded (0 if no checkpoint)."""
    if not checkpoint_path.exists():
        return 0
    try:
        with checkpoint_path.open("r") as f:
            data = json.load(f)
        pos = int(data.get("write_pos", 0))
        LOGGER.info("Encode checkpoint found — resuming from vector %d.", pos)
        return pos
    except Exception:
        return 0


def _save_encode_checkpoint(checkpoint_path: Path, write_pos: int) -> None:
    with checkpoint_path.open("w") as f:
        json.dump({"write_pos": write_pos, "timestamp": time.time()}, f)


def stream_encode_to_memmap(
    model: SentenceTransformer,
    input_path: Path,
    dimension: int,
    memmap_path: Path,
    checkpoint_path: Path,
    label: str,
    total_chunks: int,
) -> np.ndarray:
    """
    Stream texts → encode in batches → write to memmap.
    Supports resuming after a crash via checkpoint file.

    Memory profile (12.7M vectors x 768 dims):
      - Text strings in RAM : CHUNK_BATCH x ~100 words x 6 bytes ≈ 30 MB
      - GPU (one batch)     : ENCODE_BATCH x 768 x 4 bytes ≈ 1.5 MB
      - Memmap on disk      : 12.7M x 768 x 4 bytes ≈ 37 GB
    """
    size_gb = total_chunks * dimension * 4 / 1024**3
    LOGGER.info(
        "[%s] Memmap: %d vectors x %d dims = %.1f GB",
        label, total_chunks, dimension, size_gb,
    )

    # Open memmap — use r+ if resuming (file already exists), w+ if fresh
    resume_from = _load_encode_checkpoint(checkpoint_path)
    mode = "r+" if (memmap_path.exists() and resume_from > 0) else "w+"

    embeddings = np.memmap(
        str(memmap_path),
        dtype="float32",
        mode=mode,
        shape=(total_chunks, dimension),
    )

    if resume_from > 0:
        LOGGER.info("[%s] Resuming encode from position %d / %d.", label, resume_from, total_chunks)

    write_pos  = resume_from
    batch_texts: list[str] = []
    t_start    = time.time()

    def flush_batch() -> None:
        nonlocal write_pos
        if not batch_texts:
            return
        batch_emb = encode_batch_texts(model, batch_texts)
        end = write_pos + len(batch_texts)
        embeddings[write_pos:end] = batch_emb
        embeddings.flush()
        del batch_emb
        gc.collect()
        write_pos += len(batch_texts)
        batch_texts.clear()

        # Save checkpoint after every flush
        _save_encode_checkpoint(checkpoint_path, write_pos)

        # ETA estimate
        elapsed   = time.time() - t_start
        rate      = (write_pos - resume_from) / max(elapsed, 1)
        remaining = (total_chunks - write_pos) / max(rate, 1)
        LOGGER.info(
            "[%s] %d / %d  (%.1f%%)  rate=%.0f vec/s  ETA=%.0f min",
            label, write_pos, total_chunks,
            write_pos / total_chunks * 100,
            rate,
            remaining / 60,
        )

    # Skip already-encoded lines
    iter_lines = input_path.open("r", encoding="utf-8")
    if TQDM_AVAILABLE:
        iter_lines = tqdm(iter_lines, total=total_chunks, desc=f"[{label}] Encoding",
                          initial=resume_from, unit="chunk")

    line_idx = 0
    for line in iter_lines:
        if not line.strip():
            continue
        if line_idx < resume_from:
            line_idx += 1
            continue  # skip already-encoded lines

        text = json.loads(line).get("text", "")
        batch_texts.append(text)
        line_idx += 1

        if len(batch_texts) >= CHUNK_BATCH:
            flush_batch()

    flush_batch()  # flush remaining

    if TQDM_AVAILABLE and hasattr(iter_lines, "close"):
        iter_lines.close()

    LOGGER.info("[%s] Encoding complete — %d vectors.", label, write_pos)

    # Clear checkpoint — encoding is done
    if checkpoint_path.exists():
        checkpoint_path.unlink()

    return embeddings


def load_existing_memmap(memmap_path: Path, total_chunks: int, dimension: int) -> np.ndarray:
    """Load existing memmap — skips encoding entirely (use with --skip-encode)."""
    LOGGER.info("Loading existing memmap: %s", memmap_path)
    embeddings = np.memmap(
        str(memmap_path), dtype="float32", mode="r",
        shape=(total_chunks, dimension),
    )
    LOGGER.info("Loaded %d x %d vectors.", total_chunks, dimension)
    return embeddings


# ---------------------------------------------------------------------------
# Two-pass JSONL helpers
# ---------------------------------------------------------------------------

def count_and_read_metadata(
    input_path: Path,
) -> tuple[int, list[dict], dict[str, list[int]]]:
    metadata: list[dict] = []
    cat_to_indices: dict[str, list[int]] = defaultdict(list)

    LOGGER.info("Pass 1 — reading metadata from %s ...", input_path)
    with input_path.open("r", encoding="utf-8") as f:
        lines = f if not TQDM_AVAILABLE else tqdm(f, desc="Reading metadata", unit="line")
        for line in lines:
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
    LOGGER.info("Pass 1 done — %d chunks across %d categories.", total, len(cat_to_indices))
    return total, metadata, cat_to_indices


def read_texts_for_indices(input_path: Path, indices: set[int]) -> list[str]:
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
    use_gpu: bool = True,
) -> faiss.Index:
    """Train and add vectors to a FAISS index. Uses GPU if available."""
    min_vectors = 39 * nlist
    nlist_actual = nlist
    if n < min_vectors:
        nlist_actual = max(1, n // 39)
        LOGGER.warning(
            "[%s] nlist reduced %d → %d (need %d vectors, have %d)",
            label, nlist, nlist_actual, min_vectors, n,
        )

    if index_type == "pq":
        LOGGER.info("[%s] Building IVFPQ (nlist=%d, m=%d, nbits=%d) ...",
                    label, nlist_actual, pq_m, pq_nbits)
        index = build_ivfpq_index(dimension, nlist_actual, pq_m, pq_nbits)
    else:
        LOGGER.info("[%s] Building IVFFlat (nlist=%d) ...", label, nlist_actual)
        index = build_ivfflat_index(dimension, nlist_actual)

    # Move to GPU for training/adding (10x faster on A100)
    if use_gpu and torch.cuda.is_available():
        index = move_index_to_gpu(index)

    # Train on a random sample (full training rarely helps after 500K vectors)
    train_size = min(n, 500_000)
    LOGGER.info("[%s] Training on %d vectors (sample of %d) ...", label, train_size, n)
    if train_size < n:
        rng = np.random.default_rng(42)
        sample_idx  = rng.choice(n, size=train_size, replace=False)
        train_data  = np.array(embeddings[sample_idx], dtype="float32")
    else:
        train_data = np.array(embeddings[:n], dtype="float32")

    index.train(train_data)
    del train_data
    gc.collect()
    log_gpu_memory("after training")

    # Add in chunks to avoid OOM
    add_chunk = 500_000
    LOGGER.info("[%s] Adding %d vectors in chunks of %d ...", label, n, add_chunk)
    for start in range(0, n, add_chunk):
        end   = min(start + add_chunk, n)
        chunk = np.array(embeddings[start:end], dtype="float32")
        index.add(chunk)
        del chunk
        gc.collect()
        LOGGER.info("[%s] Added %d / %d vectors.", label, end, n)

    # Move back to CPU before saving (GPU indexes can't be serialised)
    if use_gpu and torch.cuda.is_available():
        LOGGER.info("[%s] Moving index back to CPU ...", label)
        index = faiss.index_gpu_to_cpu(index)
        log_gpu_memory("after index moved to CPU")

    LOGGER.info("[%s] Index built — ntotal=%d", label, index.ntotal)
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
# Post-build verification
# ---------------------------------------------------------------------------

def verify_index(
    index_path: Path,
    metadata_path: Path,
    model: SentenceTransformer | None,
    test_arxiv_id: str | None = None,
) -> bool:
    """
    Verify the built index:
    1. reconstruct() works (direct map OK)
    2. If a test_arxiv_id is given, encodes a dummy query and checks the
       paper appears in top-10 with a high score.
    """
    LOGGER.info("=" * 60)
    LOGGER.info("Verifying index ...")

    try:
        idx = faiss.read_index(str(index_path))
        LOGGER.info("  ntotal    : %d", idx.ntotal)
        LOGGER.info("  dimension : %d", idx.d)
        LOGGER.info("  type      : %s", type(idx).__name__)
    except Exception as e:
        LOGGER.error("  FAILED to load index: %s", e)
        return False

    # Test reconstruct
    try:
        vec = np.empty((idx.d,), dtype="float32")
        idx.reconstruct(0, vec)
        LOGGER.info("  reconstruct(0) : OK ✓")
    except Exception as e:
        LOGGER.error("  reconstruct FAILED: %s", e)
        return False

    with open(metadata_path, "rb") as f:
        meta = pickle.load(f)
    LOGGER.info("  metadata rows  : %d ✓", len(meta))

    # Optional score test
    if test_arxiv_id and model is not None:
        LOGGER.info("  Score test for arxiv_id=%s ...", test_arxiv_id)
        # Find a chunk from this paper to use as query
        sample_meta = next(
            (m for m in meta if test_arxiv_id in str(m.get("arxiv_id", ""))), None
        )
        if sample_meta is None:
            LOGGER.warning("  arxiv_id %s not found in metadata — skipping score test.", test_arxiv_id)
        else:
            # Use title as a proxy query (we don't have the text here)
            query_text = sample_meta.get("title", test_arxiv_id)
            vec = model.encode([query_text], normalize_embeddings=True).astype("float32")
            scores, indices = idx.search(vec, 20)
            found = [
                (float(s), meta[int(i)].get("arxiv_id"))
                for s, i in zip(scores[0], indices[0])
                if int(i) >= 0 and test_arxiv_id in str(meta[int(i)].get("arxiv_id", ""))
            ]
            if found:
                best_score = max(s for s, _ in found)
                LOGGER.info(
                    "  Score test: %s found in top-20 with score %.4f %s",
                    test_arxiv_id, best_score,
                    "✓ (good)" if best_score > 0.75 else "⚠ (low — may be PQ index)",
                )
            else:
                LOGGER.warning(
                    "  Score test: %s NOT found in top-20 — check index or routing.", test_arxiv_id
                )

    LOGGER.info("Verification complete.")
    LOGGER.info("=" * 60)
    return True


# ---------------------------------------------------------------------------
# HuggingFace upload
# ---------------------------------------------------------------------------

def upload_to_hf(
    artifacts_dir: Path,
    repo_id: str,
    hf_token: str | None,
    delete_after_upload: bool = True,
) -> None:
    """Upload index and metadata to HuggingFace, optionally freeing local disk."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        LOGGER.warning("huggingface_hub not installed — skipping upload.")
        return

    api = HfApi()
    for filename in ["faiss_document_index.bin", "faiss_metadata.pkl"]:
        path = artifacts_dir / filename
        if not path.exists():
            LOGGER.warning("Missing %s — skipping.", filename)
            continue

        size_mb = path.stat().st_size / 1024**2
        LOGGER.info("Uploading %s (%.0f MB) → %s ...", filename, size_mb, repo_id)
        api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=filename,
            repo_id=repo_id,
            repo_type="dataset",
            token=hf_token,
        )
        LOGGER.info("%s uploaded ✓", filename)

        if delete_after_upload:
            path.unlink()
            LOGGER.info("%s deleted from local disk.", filename)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build FAISS index — resumable encoding, GPU acceleration, HF upload"
    )
    parser.add_argument(
        "--input", type=Path,
        default=Path("backend/core/antiplagiator/data/processed/chunked_database.jsonl"),
    )
    parser.add_argument(
        "--artifacts-dir", type=Path,
        default=Path("backend/core/antiplagiator/artifacts"),
    )
    parser.add_argument(
        "--memmap-dir", type=Path, default=None,
        help=(
            "Directory to store the memmap file. Defaults to artifacts-dir. "
            "On Colab, use /local-scratch for 368 GB free scratch space: "
            "--memmap-dir /local-scratch"
        ),
    )
    parser.add_argument("--nlist",  type=int, default=NLIST)
    parser.add_argument("--nprobe", type=int, default=NPROBE)
    parser.add_argument("--device", type=str, default="cuda", choices=["cuda", "cpu"])
    parser.add_argument(
        "--index-type", type=str, default="flat", choices=["flat", "pq"],
        help=(
            "flat = IVFFlat, exact scores (~0.95 identical docs), ~39 GB. "
            "pq   = IVFPQ compressed (~2 GB), scores degraded to ~0.25-0.35."
        ),
    )
    parser.add_argument("--pq-m",     type=int, default=PQ_M)
    parser.add_argument("--pq-nbits", type=int, default=PQ_NBITS)
    parser.add_argument("--no-per-category", action="store_true")
    parser.add_argument(
        "--skip-encode", action="store_true",
        help="Skip encoding and load existing memmap. Saves hours if memmap already exists.",
    )
    parser.add_argument(
        "--no-gpu-index", action="store_true",
        help="Don't move index to GPU for training/adding (use if GPU OOM during index build).",
    )
    parser.add_argument(
        "--hf-repo-id", type=str, default=os.getenv("HF_REPO_ID"),
        help="HuggingFace repo ID to upload artifacts after build.",
    )
    parser.add_argument(
        "--hf-token", type=str, default=os.getenv("HF_TOKEN"),
        help="HuggingFace token (or set HF_TOKEN env var).",
    )
    parser.add_argument(
        "--verify-arxiv-id", type=str, default=None,
        help="ArXiv ID to use for post-build score verification (e.g. 2007.01684).",
    )
    parser.add_argument(
        "--no-delete-after-upload", action="store_true",
        help="Keep local copies after uploading to HuggingFace.",
    )
    args = parser.parse_args()

    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    memmap_dir = args.memmap_dir or args.artifacts_dir
    memmap_dir.mkdir(parents=True, exist_ok=True)

    device = args.device if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        gpu = torch.cuda.get_device_properties(0)
        LOGGER.info("GPU: %s (%.1f GB VRAM)", gpu.name, gpu.total_memory / 1024**3)
    else:
        LOGGER.warning("No GPU — encoding will be slow.")

    # ── Pass 1: metadata ─────────────────────────────────────────────────────
    total_chunks, all_metadata, cat_to_indices = count_and_read_metadata(args.input)

    index_path        = args.artifacts_dir / "faiss_document_index.bin"
    metadata_path     = args.artifacts_dir / "faiss_metadata.pkl"
    memmap_path       = memmap_dir / "global.memmap.npy"
    encode_checkpoint = memmap_dir / ENCODE_CHECKPOINT_FILE

    # ── Disk space check ─────────────────────────────────────────────────────
    if not args.skip_encode:
        check_disk_space(memmap_dir, total_chunks, 768, args.index_type)

    # ── Load model ───────────────────────────────────────────────────────────
    if args.skip_encode:
        if not memmap_path.exists():
            parser.error(f"--skip-encode set but memmap not found at {memmap_path}.")
        LOGGER.info("--skip-encode: loading model only for dimension detection ...")
        model = SentenceTransformer(MODEL_NAME, device="cpu")
        try:
            dimension = model.get_embedding_dimension()
        except AttributeError:
            dimension = model.get_sentence_embedding_dimension()
        verify_model = model  # keep for verification
        embeddings = load_existing_memmap(memmap_path, total_chunks, dimension)
    else:
        LOGGER.info("Loading %s on %s ...", MODEL_NAME, device)
        model = SentenceTransformer(
            MODEL_NAME,
            device=device,
            model_kwargs={"dtype": torch.float16} if device == "cuda" else {},
        )
        try:
            dimension = model.get_embedding_dimension()
        except AttributeError:
            dimension = model.get_sentence_embedding_dimension()
        LOGGER.info("Embedding dimension: %d", dimension)

        if args.index_type == "pq" and dimension % args.pq_m != 0:
            valid = [x for x in [8, 16, 32, 64, 96, 128, 192, 256] if dimension % x == 0]
            parser.error(f"--pq-m {args.pq_m} must divide dimension {dimension}. Valid: {valid}")

        embeddings = stream_encode_to_memmap(
            model, args.input, dimension,
            memmap_path, encode_checkpoint, "GLOBAL", total_chunks,
        )

        # Free model before index build — saves GPU memory for training
        LOGGER.info("Freeing model memory before index build ...")
        verify_model = model   # keep reference for post-build verification
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log_gpu_memory("after model free")

    # ── Build + save global index ─────────────────────────────────────────────
    use_gpu_index = not args.no_gpu_index
    index = build_index_from_memmap(
        embeddings, total_chunks, args.nlist,
        args.index_type, args.pq_m, args.pq_nbits, dimension, "GLOBAL",
        use_gpu=use_gpu_index,
    )
    save_index(index, all_metadata, index_path, metadata_path, "GLOBAL")

    del embeddings, index
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    try:
        memmap_path.unlink(missing_ok=True)
        LOGGER.info("Memmap deleted.")
    except Exception:
        pass

    # ── Post-build verification ───────────────────────────────────────────────
    verify_index(
        index_path, metadata_path,
        model=verify_model,
        test_arxiv_id=args.verify_arxiv_id,
    )
    del verify_model
    gc.collect()

    # ── Upload to HuggingFace ─────────────────────────────────────────────────
    if args.hf_repo_id:
        upload_to_hf(
            args.artifacts_dir,
            args.hf_repo_id,
            args.hf_token,
            delete_after_upload=not args.no_delete_after_upload,
        )
    else:
        LOGGER.info("No --hf-repo-id — skipping upload.")

    # ── Per-category indexes ──────────────────────────────────────────────────
    if not args.no_per_category:
        LOGGER.info("Loading model for per-category indexes ...")
        model = SentenceTransformer(MODEL_NAME, device=device)
        cat_dir = args.artifacts_dir / "category_indexes"
        cat_dir.mkdir(exist_ok=True)

        for cat, indices in sorted(cat_to_indices.items()):
            safe          = cat.replace("/", "_").replace(".", "_").replace("-", "_")
            cat_index_path = cat_dir / f"faiss_{safe}.bin"
            cat_meta_path  = cat_dir / f"faiss_{safe}_meta.pkl"
            cat_memmap     = memmap_dir / f"{safe}.memmap.npy"
            cat_checkpoint = memmap_dir / f"{safe}_checkpoint.json"

            cat_metadata = [all_metadata[i] for i in indices]
            n_cat = len(indices)

            LOGGER.info("[%s] %d chunks — per-category index ...", cat, n_cat)

            indices_set = set(indices)
            cat_texts   = read_texts_for_indices(args.input, indices_set)

            cat_emb = np.memmap(
                str(cat_memmap), dtype="float32", mode="w+", shape=(n_cat, dimension)
            )
            pos = 0
            for start in range(0, n_cat, CHUNK_BATCH):
                batch = cat_texts[start: start + CHUNK_BATCH]
                emb   = encode_batch_texts(model, batch)
                cat_emb[pos: pos + len(batch)] = emb
                cat_emb.flush()
                del emb
                pos += len(batch)
            del cat_texts
            gc.collect()

            cat_index = build_index_from_memmap(
                cat_emb, n_cat, args.nlist,
                "flat", args.pq_m, args.pq_nbits, dimension, cat,
                use_gpu=use_gpu_index,
            )
            save_index(cat_index, cat_metadata, cat_index_path, cat_meta_path, cat)

            del cat_emb, cat_index
            gc.collect()
            try:
                cat_memmap.unlink(missing_ok=True)
            except Exception:
                pass

    LOGGER.info("=" * 60)
    LOGGER.info("All indexes built successfully.")
    LOGGER.info("=" * 60)

    if args.index_type == "flat":
        LOGGER.info("Index type: IVFFlat — use threshold=0.75 in backend")
    else:
        LOGGER.info("Index type: IVFPQ (M=%d) — use threshold=0.20 in backend", args.pq_m)


if __name__ == "__main__":
    main()