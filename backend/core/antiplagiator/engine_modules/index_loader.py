from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Any

import faiss

LOGGER = logging.getLogger("antiplagiator.index_loader")


# ---------------------------------------------------------------------------
# Global index
# ---------------------------------------------------------------------------

def load_global_index(
    artifacts_dir: Path,
    nprobe: int,
) -> tuple["faiss.Index", list[dict[str, Any]]]:
    """
    Load the global FAISS index and its paired metadata pickle.

    Raises FileNotFoundError if either file is missing.
    """
    index_path    = artifacts_dir / "faiss_document_index.bin"
    metadata_path = artifacts_dir / "faiss_metadata.pkl"

    if not index_path.exists():
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"FAISS metadata not found: {metadata_path}")

    LOGGER.info("Loading global FAISS index from %s ...", index_path)
    index = faiss.read_index(str(index_path))
    if hasattr(index, "nprobe"):
        index.nprobe = nprobe

    with metadata_path.open("rb") as f:
        metadata: list[dict[str, Any]] = pickle.load(f)

    LOGGER.info("Global index ready — %d vectors, %d metadata rows", index.ntotal, len(metadata))
    return index, metadata


# ---------------------------------------------------------------------------
# Per-category indexes
# ---------------------------------------------------------------------------

def load_per_category_indexes(
    cat_dir: Path,
    nprobe: int,
    code_to_name: dict[str, str],
) -> tuple[dict[str, "faiss.Index"], dict[str, list[dict]]]:
    """
    Load every faiss_<code>.bin + faiss_<code>_meta.pkl found in cat_dir.

    Each index is registered under three keys so routing always finds it:
      - arXiv code   e.g. "nucl-ex"
      - human name   e.g. "Nuclear Experiment"
      - safe key     e.g. "nucl_ex"

    Returns (cat_indexes, cat_metadata).
    """
    cat_indexes:  dict[str, faiss.Index]  = {}
    cat_metadata: dict[str, list[dict]]   = {}

    if not cat_dir.exists():
        LOGGER.warning("Per-category index dir not found: %s", cat_dir)
        return cat_indexes, cat_metadata

    for index_file in cat_dir.glob("faiss_*.bin"):
        meta_file = index_file.with_name(f"{index_file.stem}_meta.pkl")
        if not meta_file.exists():
            LOGGER.warning("Missing metadata for %s — skipping", index_file.name)
            continue

        idx = faiss.read_index(str(index_file))
        if hasattr(idx, "nprobe"):
            idx.nprobe = nprobe

        with meta_file.open("rb") as f:
            meta = pickle.load(f)

        file_key = index_file.stem[len("faiss_"):]                # e.g. "nucl-ex"
        name_key = code_to_name.get(file_key, file_key)           # e.g. "Nuclear Experiment"
        safe_key = file_key.replace("-", "_").replace(".", "_")    # e.g. "nucl_ex"

        for key in {file_key, name_key, safe_key}:
            cat_indexes[key]  = idx
            cat_metadata[key] = meta

        LOGGER.info(
            "Loaded per-category index: %s → '%s' (%d vectors)",
            file_key, name_key, idx.ntotal,
        )

    return cat_indexes, cat_metadata


# ---------------------------------------------------------------------------
# Dataset text helpers
# ---------------------------------------------------------------------------

def load_dataset_texts(jsonl_path: Path) -> list[str]:
    """Read chunked_database.jsonl and return the 'text' field for every row."""
    texts: list[str] = []
    if not jsonl_path.exists():
        LOGGER.warning("Dataset JSONL not found: %s", jsonl_path)
        return texts
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                texts.append(str(json.loads(line).get("text", "")))
    LOGGER.info("Loaded %d dataset texts from %s", len(texts), jsonl_path)
    return texts


def build_text_lookup(
    texts: list[str],
    metadata: list[dict[str, Any]],
) -> dict[tuple[str, int], str]:
    """
    Build a (arxiv_id, chunk_id) -> text mapping.

    Per-category metadata may have the text field stripped; this lookup
    bridges that gap without requiring a FAISS rebuild.
    """
    lookup: dict[tuple[str, int], str] = {}
    for text, meta in zip(texts, metadata):
        key = (str(meta.get("arxiv_id", "")), int(meta.get("chunk_id", -1)))
        lookup[key] = text
    LOGGER.info("Text lookup table ready — %d entries", len(lookup))
    return lookup