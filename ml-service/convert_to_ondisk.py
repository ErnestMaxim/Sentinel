"""
convert_to_ondisk.py
====================
Converts the IVFFlat index to OnDiskInvertedLists format so it can be
searched without loading the full 36 GB into RAM.

Result:
  - faiss_document_index_ondisk.bin  (~few MB — just the quantizer + config)
  - faiss_ondisk.ivf                 (~36 GB — vectors stored on disk)

At search time FAISS reads only the inverted lists it needs (nprobe=64 out of
1024 lists), so RAM usage stays under ~2 GB instead of 36 GB.

Usage:
    cd ml-service
    python convert_to_ondisk.py

Expected time: 20-60 minutes depending on pagefile/SSD speed.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import faiss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
LOGGER = logging.getLogger("convert_to_ondisk")

ARTIFACTS_DIR    = Path("artifacts")
SRC_INDEX        = ARTIFACTS_DIR / "faiss_document_index.bin"
ONDISK_IVF       = ARTIFACTS_DIR / "faiss_ondisk.ivf"
DST_INDEX        = ARTIFACTS_DIR / "faiss_document_index_ondisk.bin"
NPROBE           = 64


def main() -> None:
    # ── Sanity checks ────────────────────────────────────────────────────────
    if not SRC_INDEX.exists():
        LOGGER.error("Source index not found: %s", SRC_INDEX.absolute())
        LOGGER.error("Run from the ml-service/ directory where artifacts/ lives.")
        sys.exit(1)

    src_gb = SRC_INDEX.stat().st_size / 1024**3
    LOGGER.info("Source index : %s (%.1f GB)", SRC_INDEX, src_gb)
    LOGGER.info("Output index : %s", DST_INDEX)
    LOGGER.info("Output IVF   : %s", ONDISK_IVF)
    LOGGER.info("")
    LOGGER.info("This will load the full index via Windows virtual memory.")
    LOGGER.info("Expected time: 20-60 minutes. Do not interrupt.")
    LOGGER.info("")

    # Delete existing ondisk files to avoid corruption
    if ONDISK_IVF.exists():
        LOGGER.info("Removing existing %s ...", ONDISK_IVF)
        ONDISK_IVF.unlink()
    if DST_INDEX.exists():
        LOGGER.info("Removing existing %s ...", DST_INDEX)
        DST_INDEX.unlink()

    # ── Step 1: Load source index ─────────────────────────────────────────────
    LOGGER.info("=" * 60)
    LOGGER.info("Step 1/3 — Loading source IVFFlat index into virtual memory...")
    LOGGER.info("(Windows will page this through the pagefile — be patient)")
    LOGGER.info("=" * 60)

    t0 = time.time()
    try:
        index = faiss.read_index(str(SRC_INDEX))
    except Exception as e:
        LOGGER.error("Failed to load index: %s", e)
        LOGGER.error("Make sure pagefile is at least 40 GB (currently set to 37.4 GB).")
        sys.exit(1)

    elapsed = time.time() - t0
    LOGGER.info("Index loaded in %.1f minutes.", elapsed / 60)
    LOGGER.info("  ntotal    : %d", index.ntotal)
    LOGGER.info("  nlist     : %d", index.nlist)
    LOGGER.info("  dimension : %d", index.d)
    LOGGER.info("  type      : %s", type(index).__name__)

    if not isinstance(index, faiss.IndexIVFFlat):
        LOGGER.error("Expected IndexIVFFlat but got %s.", type(index).__name__)
        LOGGER.error("This script only converts IVFFlat indexes.")
        sys.exit(1)

    # ── Step 2: Convert inverted lists to on-disk format ─────────────────────
    LOGGER.info("")
    LOGGER.info("=" * 60)
    LOGGER.info("Step 2/3 — Converting inverted lists to OnDisk format...")
    LOGGER.info("Writing to: %s", ONDISK_IVF)
    LOGGER.info("=" * 60)

    t1 = time.time()
    try:
        invlists = faiss.OnDiskInvertedLists(
            index.nlist,
            index.code_size,
            str(ONDISK_IVF),
        )
        index.replace_invlists(invlists, True)
    except Exception as e:
        LOGGER.error("Failed to convert inverted lists: %s", e)
        sys.exit(1)

    elapsed = time.time() - t1
    LOGGER.info("Conversion done in %.1f minutes.", elapsed / 60)
    ivf_gb = ONDISK_IVF.stat().st_size / 1024**3
    LOGGER.info("IVF file size: %.1f GB", ivf_gb)

    # ── Step 3: Save new index ────────────────────────────────────────────────
    LOGGER.info("")
    LOGGER.info("=" * 60)
    LOGGER.info("Step 3/3 — Saving new index (tiny — just quantizer + config)...")
    LOGGER.info("=" * 60)

    t2 = time.time()
    try:
        faiss.write_index(index, str(DST_INDEX))
    except Exception as e:
        LOGGER.error("Failed to save index: %s", e)
        sys.exit(1)

    elapsed = time.time() - t2
    dst_mb = DST_INDEX.stat().st_size / 1024**2
    LOGGER.info("Saved in %.1fs — size: %.1f MB", elapsed, dst_mb)

    # ── Verify ────────────────────────────────────────────────────────────────
    LOGGER.info("")
    LOGGER.info("=" * 60)
    LOGGER.info("Verifying ondisk index loads correctly...")
    LOGGER.info("=" * 60)

    try:
        test_idx = faiss.read_index(str(DST_INDEX))
        test_idx.nprobe = NPROBE
        LOGGER.info("  ntotal : %d ✓", test_idx.ntotal)
        LOGGER.info("  type   : %s ✓", type(test_idx).__name__)

        import numpy as np
        dummy = np.random.randn(1, test_idx.d).astype("float32")
        faiss.normalize_L2(dummy)
        scores, indices = test_idx.search(dummy, 5)
        LOGGER.info("  test search: top score=%.4f ✓", float(scores[0][0]))
    except Exception as e:
        LOGGER.error("Verification failed: %s", e)
        sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = time.time() - t0
    LOGGER.info("")
    LOGGER.info("=" * 60)
    LOGGER.info("Conversion complete in %.1f minutes.", total / 60)
    LOGGER.info("")
    LOGGER.info("Files created:")
    LOGGER.info("  %s  (%.1f MB) — load this in index_loader.py",
                DST_INDEX, DST_INDEX.stat().st_size / 1024**2)
    LOGGER.info("  %s  (%.1f GB) — keep this next to the index",
                ONDISK_IVF, ONDISK_IVF.stat().st_size / 1024**3)
    LOGGER.info("")
    LOGGER.info("Next step — update index_loader.py:")
    LOGGER.info('  Change: faiss.read_index(str(index_path))')
    LOGGER.info('  To    : faiss.read_index(str(index_path))  # point to _ondisk.bin')
    LOGGER.info("")
    LOGGER.info("And update ARTIFACTS_DIR in ml-service/.env to use:")
    LOGGER.info("  faiss_document_index_ondisk.bin  (not faiss_document_index.bin)")
    LOGGER.info("=" * 60)


if __name__ == "__main__":
    main()