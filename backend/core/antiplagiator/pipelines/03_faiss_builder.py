"""
03_faiss_builder.py — incremental version.

New flag: --incremental
  When set, loads the existing global FAISS index + metadata, encodes only
  the new chunks from chunked_database.jsonl (those whose arxiv_id is not
  already in the metadata), and adds them to the existing index.
  
  This avoids a full 13h rebuild every time you add papers.
  The IVFFlat index supports add() on a trained index without retraining.

  Per-category indexes are rebuilt from scratch (they're small and fast).

Usage (first build):
  python 03_faiss_builder.py --device cuda

Usage (after adding new papers):
  python 03_faiss_builder.py --device cuda --incremental
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
NLIST        = 100
NPROBE       = 20
CHUNK_BATCH  = 50_000
ENCODE_BATCH = 256


def build_ivf_index(dimension: int, nlist: int) -> faiss.IndexIVFFlat:
    quantizer = faiss.IndexFlatIP(dimension)
    index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
    index.nprobe = NPROBE
    return index


def encode_batch(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    with torch.no_grad():
        embeddings = model.encode(
            texts,
            batch_size=ENCODE_BATCH,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    torch.cuda.empty_cache()
    return embeddings


def load_existing_arxiv_ids(metadata: list[dict]) -> set[str]:
    """Return the set of arxiv_ids already present in the FAISS metadata."""
    return {str(m.get("arxiv_id", "")) for m in metadata}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build / incrementally update FAISS indexes"
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
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument(
        "--no-per-category", action="store_true",
        help="Skip building per-category indexes",
    )
    parser.add_argument(
        "--incremental", action="store_true",
        help=(
            "Load existing global index and append only new chunks. "
            "Per-category indexes are always fully rebuilt (they are fast). "
            "Use this after running 01_extractor + 02_chunker with --incremental."
        ),
    )
    args = parser.parse_args()

    args.artifacts_dir.mkdir(parents=True, exist_ok=True)

    device = args.device if torch.cuda.is_available() else "cpu"
    LOGGER.info("Loading model %s on %s", MODEL_NAME, device)
    model = SentenceTransformer(
        MODEL_NAME,
        device=device,
        model_kwargs={"dtype": torch.float16} if device == "cuda" else {},
    )
    dimension = model.get_sentence_embedding_dimension()
    LOGGER.info("Embedding dimension: %d", dimension)

    index_path    = args.artifacts_dir / "faiss_document_index.bin"
    metadata_path = args.artifacts_dir / "faiss_metadata.pkl"

    if args.incremental and index_path.exists() and metadata_path.exists():
        LOGGER.info("Incremental mode — loading existing global index ...")
        global_index = faiss.read_index(str(index_path))
        if hasattr(global_index, "nprobe"):
            global_index.nprobe = args.nprobe
        with metadata_path.open("rb") as f:
            global_metadata: list[dict] = pickle.load(f)
        existing_ids = load_existing_arxiv_ids(global_metadata)
        LOGGER.info(
            "Existing index: %d vectors, %d unique arxiv_ids",
            global_index.ntotal, len(existing_ids),
        )
    else:
        if args.incremental:
            LOGGER.warning(
                "Incremental requested but no existing index found — doing full build."
            )
        global_index    = None
        global_metadata = []
        existing_ids    = set()

    LOGGER.info("Reading %s ...", args.input)
    by_category: dict[str, list[dict]] = defaultdict(list)
    new_records: list[dict] = []   # chunks not yet in the index
    all_records: list[dict] = []   # all chunks (for per-category rebuild)

    with args.input.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            record = {
                "arxiv_id":     data["arxiv_id"],
                "title":        data["title"],
                "chunk_id":     data["chunk_id"],
                "source_type":  data.get("source_type", "unknown"),
                "top_category": data.get("top_category", "unknown"),
                "text":         data["text"],
            }
            all_records.append(record)
            by_category[record["top_category"]].append(record)

            if record["arxiv_id"] not in existing_ids:
                new_records.append(record)

    LOGGER.info(
        "Total chunks: %d | New (not yet indexed): %d",
        len(all_records), len(new_records),
    )

    def build_and_save(
        records: list[dict],
        index_path: Path,
        metadata_path: Path,
        label: str,
    ) -> None:
        texts    = [r["text"] for r in records]
        metadata = [{k: v for k, v in r.items() if k != "text"} for r in records]

        LOGGER.info("[%s] Encoding %d chunks ...", label, len(texts))
        all_embeddings: list[np.ndarray] = []
        for start in range(0, len(texts), CHUNK_BATCH):
            batch = texts[start: start + CHUNK_BATCH]
            all_embeddings.append(encode_batch(model, batch))
            LOGGER.info(
                "[%s] Encoded %d / %d",
                label, min(start + CHUNK_BATCH, len(texts)), len(texts),
            )

        embeddings = np.vstack(all_embeddings).astype("float32")

        nlist_actual = min(args.nlist, len(embeddings) // 10 or 1)
        if nlist_actual < args.nlist:
            LOGGER.warning(
                "[%s] nlist reduced from %d to %d (too few vectors)",
                label, args.nlist, nlist_actual,
            )

        LOGGER.info("[%s] Training IVFFlat index (nlist=%d) ...", label, nlist_actual)
        index = build_ivf_index(dimension, nlist_actual)
        index.train(embeddings)
        index.add(embeddings)

        faiss.write_index(index, str(index_path))
        with metadata_path.open("wb") as f:
            pickle.dump(metadata, f)
        LOGGER.info("[%s] Done — %d vectors indexed.", label, index.ntotal)

    if args.incremental and global_index is not None:
        if not new_records:
            LOGGER.info("No new chunks to add to the global index. Skipping encode.")
        else:
            new_texts = [r["text"] for r in new_records]
            new_meta  = [{k: v for k, v in r.items() if k != "text"} for r in new_records]

            LOGGER.info("Encoding %d new chunks for incremental add ...", len(new_texts))
            all_new_embeddings: list[np.ndarray] = []
            for start in range(0, len(new_texts), CHUNK_BATCH):
                batch = new_texts[start: start + CHUNK_BATCH]
                all_new_embeddings.append(encode_batch(model, batch))
                LOGGER.info(
                    "Encoded %d / %d new chunks",
                    min(start + CHUNK_BATCH, len(new_texts)), len(new_texts),
                )

            new_embeddings = np.vstack(all_new_embeddings).astype("float32")

            LOGGER.info(
                "Adding %d new vectors to existing index (was %d) ...",
                len(new_embeddings), global_index.ntotal,
            )
            global_index.add(new_embeddings)
            global_metadata.extend(new_meta)

            faiss.write_index(global_index, str(index_path))
            with metadata_path.open("wb") as f:
                pickle.dump(global_metadata, f)
            LOGGER.info(
                "Global index updated — now %d vectors total.", global_index.ntotal
            )
    else:
        build_and_save(
            records=all_records,
            index_path=index_path,
            metadata_path=metadata_path,
            label="GLOBAL",
        )

    if not args.no_per_category:
        cat_dir = args.artifacts_dir / "category_indexes"
        cat_dir.mkdir(exist_ok=True)
        for cat, records in by_category.items():
            safe_name = cat.replace("/", "_").replace(".", "_").replace("-", "_")
            build_and_save(
                records=records,
                index_path=cat_dir / f"faiss_{safe_name}.bin",
                metadata_path=cat_dir / f"faiss_{safe_name}_meta.pkl",
                label=cat,
            )

    LOGGER.info("All indexes built/updated successfully.")


if __name__ == "__main__":
    main()