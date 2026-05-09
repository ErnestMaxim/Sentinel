"""
migrate_checkpoint.py — run this LOCALLY before uploading to Colab.

What it does:
  1. Reads your existing arxiv_dataset.jsonl (the raw paper metadata you
     already fetched) and converts it into the new checkpoint format
     (checkpoint_raw.jsonl) that 01_extractor.py --resume expects.

  2. Reads your old progress JSON (the per-category offset/count tracker)
     and marks categories as "completed" if they already hit their OLD target.
     Categories that are still below the NEW target are left un-completed
     so the extractor tops them up.

  3. Reports exactly what will happen when you run the extractor on Colab
     so there are no surprises.

After running this script, upload to Colab:
  - checkpoint_raw.jsonl           (generated here)
  - checkpoint_raw.completed.json  (generated here)
  - arxiv_dataset.jsonl            (your existing file, unchanged)
  - chunked_database.jsonl         (your existing file, unchanged)
  - arxiv_hierarchy.json
  - 01_extractor.py
  - 02_chunker.py
  - 03_faiss_builder.py

Usage:
  python migrate_checkpoint.py
  python migrate_checkpoint.py --progress path/to/your/progress.json
  python migrate_checkpoint.py --dry-run   (just shows what would happen)
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger("migrate")

# ---------------------------------------------------------------------------
# New targets (must match 01_extractor.py CATEGORY_TARGETS)
# ---------------------------------------------------------------------------

NEW_TARGETS: dict[str, int] = {
    "cs":       20_000,
    "eess":      8_000,
    "stat":      8_000,
    "q-bio":     5_000,
    "q-fin":     5_000,
    "nlin":      5_000,
    "econ":      5_000,
    "cond-mat":  8_000,
    "physics":   8_000,
    "math":      8_000,
    "nucl-th":   6_000,
    "math-ph":   5_000,
    "nucl-ex":   3_000,
    "hep-ex":    3_000,
    "hep-lat":   2_000,
    "astro-ph":  6_000,
    "quant-ph":  5_000,
    "hep-ph":    4_000,
    "hep-th":    4_000,
    "gr-qc":     3_000,
}


def normalise_arxiv_id(raw_id: str) -> str:
    """Strip version suffix: '2511.05984v1' → '2511.05984'."""
    base = raw_id.rsplit("/", 1)[-1]
    if "v" in base:
        base = base.rsplit("v", 1)[0]
    return base.strip()


def top_category_from_primary(primary: str) -> str:
    """'cs.AI' → 'cs',  'hep-ph' → 'hep-ph'."""
    return primary.split(".")[0].strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate old extractor state to new checkpoint format")
    parser.add_argument(
        "--dataset", type=Path,
        default=Path("backend/core/antiplagiator/data/raw/arxiv_dataset.jsonl"),
        help="Your existing raw paper metadata JSONL",
    )
    parser.add_argument(
        "--progress", type=Path,
        default=None,
        help="Your old progress JSON file (offset/count per category). Auto-detected if not set.",
    )
    parser.add_argument(
        "--outdir", type=Path,
        default=Path("backend/core/antiplagiator/data/raw"),
        help="Where to write checkpoint_raw.jsonl and checkpoint_raw.completed.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without writing any files",
    )
    args = parser.parse_args()

    # ── Auto-detect progress file ─────────────────────────────────────────
    progress_path = args.progress
    if progress_path is None:
        candidates = [
            args.outdir / "category_state.json",
            args.outdir / "progress.json",
            args.outdir / "fetch_progress.json",
            args.outdir.parent / "progress.json",
        ]
        for c in candidates:
            if c.exists():
                progress_path = c
                LOGGER.info("Auto-detected progress file: %s", c)
                break

    # ── Load old progress ─────────────────────────────────────────────────
    old_progress: dict[str, dict] = {}
    if progress_path and progress_path.exists():
        with progress_path.open("r", encoding="utf-8") as f:
            old_progress = json.load(f)
        LOGGER.info("Loaded old progress: %d categories", len(old_progress))
    else:
        LOGGER.warning(
            "No progress file found. Will infer state from arxiv_dataset.jsonl only."
        )

    # ── Load existing dataset ─────────────────────────────────────────────
    if not args.dataset.exists():
        LOGGER.error("Dataset not found: %s", args.dataset)
        return

    LOGGER.info("Reading %s ...", args.dataset)
    raw_records: list[dict] = []
    seen_ids: set[str] = set()
    cat_counts: dict[str, int] = {}

    with args.dataset.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)

            # Normalise the arxiv_id
            raw_id = str(record.get("arxiv_id", ""))
            norm_id = normalise_arxiv_id(raw_id)
            record["arxiv_id"] = norm_id

            if norm_id and norm_id not in seen_ids:
                seen_ids.add(norm_id)
                raw_records.append(record)

                primary = str(record.get("primary_category", ""))
                top_cat = top_category_from_primary(primary)
                cat_counts[top_cat] = cat_counts.get(top_cat, 0) + 1

    LOGGER.info("Loaded %d unique papers from dataset", len(raw_records))

    # ── Determine which categories are "completed" ────────────────────────
    # A category is completed if the number of papers we have for it
    # is >= the NEW target. Otherwise the extractor will top it up.
    completed: list[str] = []
    needs_topup: dict[str, dict] = {}

    all_cats = set(NEW_TARGETS.keys()) | set(cat_counts.keys())

    LOGGER.info("\n%-15s %8s %8s %10s  %s", "Category", "Have", "Target", "Need", "Status")
    LOGGER.info("-" * 60)

    for cat in sorted(all_cats):
        have   = cat_counts.get(cat, 0)
        target = NEW_TARGETS.get(cat, 500)
        need   = max(0, target - have)

        if have >= target:
            status = "✓ complete"
            completed.append(cat)
        elif have == 0:
            status = "✗ empty — full fetch needed"
            needs_topup[cat] = {"have": have, "target": target, "need": need}
        else:
            status = f"↑ top up needed"
            needs_topup[cat] = {"have": have, "target": target, "need": need}

        LOGGER.info("%-15s %8d %8d %10d  %s", cat, have, target, need, status)

    total_need = sum(v["need"] for v in needs_topup.values())
    LOGGER.info("\nCategories already complete: %d", len(completed))
    LOGGER.info("Categories needing top-up:   %d", len(needs_topup))
    LOGGER.info("Total additional papers needed: ~%d", total_need)
    LOGGER.info(
        "Estimated Colab time: ~%.1f hours (at 100 papers/min arXiv API rate)",
        total_need / 6000,
    )

    if args.dry_run:
        LOGGER.info("\nDry run — no files written.")
        return

    # ── Write checkpoint_raw.jsonl ────────────────────────────────────────
    checkpoint_path = args.outdir / "checkpoint_raw.jsonl"
    args.outdir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("\nWriting checkpoint: %s", checkpoint_path)
    with checkpoint_path.open("w", encoding="utf-8") as f:
        for record in raw_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    LOGGER.info("Wrote %d records to checkpoint", len(raw_records))

    # ── Write checkpoint_raw.completed.json ──────────────────────────────
    completed_path = checkpoint_path.with_suffix(".completed.json")
    with completed_path.open("w", encoding="utf-8") as f:
        json.dump(sorted(completed), f, indent=2)
    LOGGER.info("Marked %d categories as completed: %s", len(completed), sorted(completed))

    # ── Summary ───────────────────────────────────────────────────────────
    LOGGER.info("\n" + "=" * 60)
    LOGGER.info("Migration complete. Upload these files to Colab:")
    LOGGER.info("  %s  (%.1f MB)", checkpoint_path,
                checkpoint_path.stat().st_size / 1024**2)
    LOGGER.info("  %s", completed_path)
    LOGGER.info("  %s  (unchanged)", args.dataset)
    LOGGER.info("\nThe extractor will run with --resume and skip:")
    for cat in sorted(completed):
        LOGGER.info("  %-15s (already have %d >= %d target)",
                    cat, cat_counts.get(cat, 0), NEW_TARGETS.get(cat, 0))
    LOGGER.info("\nAnd will fetch new papers for:")
    for cat, info in sorted(needs_topup.items()):
        LOGGER.info("  %-15s (have %d, need %d more to reach %d)",
                    cat, info["have"], info["need"], info["target"])


if __name__ == "__main__":
    main()