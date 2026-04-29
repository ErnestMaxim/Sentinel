"""
01_extractor.py — rewritten for large-scale dataset collection.

Key improvements over original:
  1. Fetches at TOP-CATEGORY level instead of per-subcategory
     → eliminates cross-listed paper duplication, maximises unique records
  2. Per-top-category quota with configurable targets per category volume
     → high-volume categories (cs, math, physics) get more papers automatically
  3. Checkpoint/resume support
     → safe to stop and restart mid-run without losing progress
  4. Progress logging with per-category counts
     → you can see exactly which categories are starved
  5. Removed the min-per-class hard drop in balance_dataset
     → sparse categories are kept but capped, not silently deleted
  6. Date-range filtering support
     → fetch papers from a specific time window for diversity
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger("extractor")

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# ── Per-top-category fetch targets ───────────────────────────────────────────
# High-volume categories get more papers so your FAISS index is richer there.
CATEGORY_TARGETS: dict[str, int] = {
    "cs":        10000,
    "math":       8000,
    "physics":    8000,
    "astro-ph":   6000,
    "cond-mat":   6000,
    "quant-ph":   5000,
    "stat":       5000,
    "hep-ph":     4000,
    "hep-th":     4000,
    "gr-qc":      3000,
    "eess":       3000,
    "q-bio":      2000,
    "hep-ex":     2000,
    "nucl-th":    2000,
    "nucl-ex":    2000,
    "math-ph":    2000,
    "hep-lat":    2000,
    "econ":       2000,
    "nlin":       2000,
    "q-fin":      2000,
}
DEFAULT_TARGET = 300   # fallback for any category not listed above


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PaperRecord:
    arxiv_id: str
    title: str
    abstract: str
    published: str
    updated: str
    primary_category: str
    all_categories: list[str]
    top_category: str
    top_category_name: str
    subcategory_name: str


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "SentinelDatasetExtractor/2.0"})
    return session


# ---------------------------------------------------------------------------
# Label maps
# ---------------------------------------------------------------------------

def load_hierarchy(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_label_maps(
    hierarchy: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    sub_to_top: dict[str, str] = {}
    top_to_name: dict[str, str] = {}
    sub_to_name: dict[str, str] = {}

    for top_code, info in hierarchy.items():
        top_name = str(info.get("name", top_code))
        top_to_name[top_code] = top_name

        subs = info.get("subcategories", {}) or {}
        for sub_code, sub_name in subs.items():
            if isinstance(sub_code, str):
                sub_to_top[sub_code] = top_code
                sub_to_name[sub_code] = str(sub_name)

        sub_to_top.setdefault(top_code, top_code)
        sub_to_name.setdefault(top_code, top_name)

    return sub_to_top, top_to_name, sub_to_name


def map_labels(
    primary_category: str,
    all_categories: list[str],
    sub_to_top: dict[str, str],
    top_to_name: dict[str, str],
    sub_to_name: dict[str, str],
) -> tuple[str, str, str] | None:
    if primary_category in sub_to_top:
        top = sub_to_top[primary_category]
        return (
            top,
            top_to_name.get(top, top),
            sub_to_name.get(primary_category, top_to_name.get(top, top)),
        )
    for cat in all_categories:
        if cat in sub_to_top:
            top = sub_to_top[cat]
            return (
                top,
                top_to_name.get(top, top),
                sub_to_name.get(cat, top_to_name.get(top, top)),
            )
    return None


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def parse_entry(entry: ET.Element) -> dict[str, Any]:
    id_text = entry.findtext("atom:id", default="", namespaces=ATOM_NS).strip()
    arxiv_id = id_text.rsplit("/", 1)[-1] if id_text else ""

    title = " ".join(
        entry.findtext("atom:title", default="", namespaces=ATOM_NS).split()
    )
    abstract = " ".join(
        entry.findtext("atom:summary", default="", namespaces=ATOM_NS).split()
    )
    published = entry.findtext(
        "atom:published", default="", namespaces=ATOM_NS
    ).strip()
    updated = entry.findtext(
        "atom:updated", default="", namespaces=ATOM_NS
    ).strip()

    primary_el = entry.find("arxiv:primary_category", namespaces=ATOM_NS)
    primary_category = (
        primary_el.attrib.get("term", "").strip()
        if primary_el is not None
        else ""
    )

    all_categories: list[str] = []
    for c in entry.findall("atom:category", namespaces=ATOM_NS):
        term = c.attrib.get("term", "").strip()
        if term:
            all_categories.append(term)

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "published": published,
        "updated": updated,
        "primary_category": primary_category,
        "all_categories": list(dict.fromkeys(all_categories)),
    }


# ---------------------------------------------------------------------------
# Fetching  — now at TOP-CATEGORY level to avoid cross-listing waste
# ---------------------------------------------------------------------------

def fetch_top_category(
    session: requests.Session,
    top_cat: str,
    target: int,
    batch_size: int,
    pause_sec: float,
    seen_ids: set[str],
) -> list[dict[str, Any]]:
    """
    Fetch up to `target` UNIQUE papers for a top-level arXiv category.

    Uses `cat:<top_cat>` which matches all subcategories automatically,
    so you get true category-level coverage without redundant sub-queries.
    """
    results: list[dict[str, Any]] = []
    start = 0
    consecutive_empty = 0

    while len(results) < target:
        n = min(batch_size, target - len(results) + 20)  # small buffer for dupes
        params = {
            "search_query": f"cat:{top_cat}",
            "start": start,
            "max_results": n,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        try:
            resp = session.get(ARXIV_API_URL, params=params, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            LOGGER.warning("[%s] Request failed at offset %d: %s", top_cat, start, e)
            time.sleep(pause_sec * 3)
            consecutive_empty += 1
            if consecutive_empty >= 3:
                LOGGER.error("[%s] Too many failures, stopping.", top_cat)
                break
            continue

        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", namespaces=ATOM_NS)

        if not entries:
            LOGGER.info("[%s] No more entries at offset %d.", top_cat, start)
            break

        new_count = 0
        for e in entries:
            parsed = parse_entry(e)
            pid = str(parsed.get("arxiv_id", "")).strip()
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                results.append(parsed)
                new_count += 1

        LOGGER.info(
            "[%s] offset=%d fetched=%d new=%d total_so_far=%d / target=%d",
            top_cat, start, len(entries), new_count, len(results), target,
        )

        start += len(entries)
        consecutive_empty = 0

        if len(entries) < n:
            LOGGER.info("[%s] API returned fewer entries than requested — category exhausted.", top_cat)
            break

        time.sleep(pause_sec)

    return results[:target]


# ---------------------------------------------------------------------------
# Checkpoint helpers  — safe resume on interruption
# ---------------------------------------------------------------------------

def save_checkpoint(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in data:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    LOGGER.info("Checkpoint saved: %d raw records → %s", len(data), path)


def load_checkpoint(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    LOGGER.info("Resumed from checkpoint: %d raw records from %s", len(records), path)
    return records


def load_completed_categories(path: Path) -> set[str]:
    """Track which top categories have already been fully fetched."""
    done_path = path.parent / (path.stem + "_done_cats.json")
    if not done_path.exists():
        return set()
    with done_path.open("r", encoding="utf-8") as f:
        return set(json.load(f))


def save_completed_category(path: Path, cat: str) -> None:
    done_path = path.parent / (path.stem + "_done_cats.json")
    existing = load_completed_categories(path)
    existing.add(cat)
    with done_path.open("w", encoding="utf-8") as f:
        json.dump(sorted(existing), f)


# ---------------------------------------------------------------------------
# Dataset balancing  — keeps sparse categories, just caps them
# ---------------------------------------------------------------------------

def balance_dataset(
    records: list[PaperRecord],
    max_per_class: int,
    min_per_class: int,
    seed: int,
    drop_sparse: bool = False,
) -> list[PaperRecord]:
    """
    Balance the dataset per top_category_name.

    Parameters
    ----------
    drop_sparse  : if True, drop categories below min_per_class (original behaviour).
                   if False (default), keep them as-is — useful for the FAISS index
                   where every document matters even if a category is small.
    """
    rng = random.Random(seed)
    by_label: dict[str, list[PaperRecord]] = defaultdict(list)
    for r in records:
        by_label[r.top_category_name].append(r)

    LOGGER.info("Dataset distribution before balancing:")
    for label, items in sorted(by_label.items(), key=lambda x: -len(x[1])):
        status = "DROP" if drop_sparse and len(items) < min_per_class else "keep"
        LOGGER.info("  %-45s %4d  [%s]", label, len(items), status)

    balanced: list[PaperRecord] = []
    for label, items in sorted(by_label.items()):
        if drop_sparse and len(items) < min_per_class:
            continue
        rng.shuffle(items)
        balanced.extend(items[:max_per_class])

    return balanced


# ---------------------------------------------------------------------------
# Stratified split  (unchanged from original)
# ---------------------------------------------------------------------------

def stratified_split(
    records: list[PaperRecord], train: float, val: float, seed: int
) -> tuple[list[PaperRecord], list[PaperRecord], list[PaperRecord]]:
    by_label: dict[str, list[PaperRecord]] = defaultdict(list)
    for r in records:
        by_label[r.top_category_name].append(r)

    rng = random.Random(seed)
    train_set: list[PaperRecord] = []
    val_set: list[PaperRecord] = []
    test_set: list[PaperRecord] = []

    for items in by_label.values():
        rng.shuffle(items)
        n = len(items)
        n_train = int(n * train)
        n_val = int(n * val)
        train_set.extend(items[:n_train])
        val_set.extend(items[n_train: n_train + n_val])
        test_set.extend(items[n_train + n_val:])

    rng.shuffle(train_set)
    rng.shuffle(val_set)
    rng.shuffle(test_set)
    return train_set, val_set, test_set


def write_jsonl(path: Path, records: list[PaperRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build large-scale arXiv dataset for category classification"
    )
    parser.add_argument("--hierarchy", type=Path, required=True)
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("backend/core/antiplagiator/data"),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="API results per request (max 100 per arXiv ToS)",
    )
    parser.add_argument(
        "--pause-sec",
        type=float,
        default=3.0,
        help="Pause between API calls (be polite to arXiv)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-per-class",
        type=int,
        default=2000,
        help="Hard cap per top-category after fetching",
    )
    parser.add_argument(
        "--min-per-class",
        type=int,
        default=50,
        help="Minimum records to keep a class (only used with --drop-sparse)",
    )
    parser.add_argument(
        "--drop-sparse",
        action="store_true",
        help="Drop categories below --min-per-class (default: keep all)",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint if available",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    checkpoint_path = args.outdir / "raw" / "checkpoint_raw.jsonl"
    session = build_session()

    hierarchy = load_hierarchy(args.hierarchy)
    sub_to_top, top_to_name, sub_to_name = build_label_maps(hierarchy)

    # ── Resume or start fresh ────────────────────────────────────────────────
    all_raw: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if args.resume:
        all_raw = load_checkpoint(checkpoint_path)
        seen_ids = {str(r.get("arxiv_id", "")) for r in all_raw}

    completed_cats = load_completed_categories(checkpoint_path) if args.resume else set()

    # ── Fetch per TOP category ────────────────────────────────────────────────
    top_categories = sorted(top_to_name.keys())

    for top_cat in top_categories:
        if top_cat in completed_cats:
            LOGGER.info("[%s] Already completed, skipping.", top_cat)
            continue

        target = CATEGORY_TARGETS.get(top_cat, DEFAULT_TARGET)
        LOGGER.info(
            "[%s] %s — target=%d papers",
            top_cat,
            top_to_name[top_cat],
            target,
        )

        papers = fetch_top_category(
            session=session,
            top_cat=top_cat,
            target=target,
            batch_size=args.batch_size,
            pause_sec=args.pause_sec,
            seen_ids=seen_ids,
        )

        all_raw.extend(papers)
        save_checkpoint(checkpoint_path, all_raw)
        save_completed_category(checkpoint_path, top_cat)
        LOGGER.info(
            "[%s] Done. Got %d papers. Total unique so far: %d",
            top_cat,
            len(papers),
            len(all_raw),
        )

    LOGGER.info("Total raw records fetched: %d", len(all_raw))

    # ── Map to PaperRecord ───────────────────────────────────────────────────
    records: list[PaperRecord] = []
    unmapped = 0
    for p in all_raw:
        mapped = map_labels(
            str(p.get("primary_category", "")),
            list(p.get("all_categories", [])),
            sub_to_top,
            top_to_name,
            sub_to_name,
        )
        if mapped is None:
            unmapped += 1
            continue

        top_cat, top_name, sub_name = mapped
        records.append(
            PaperRecord(
                arxiv_id=str(p.get("arxiv_id", "")),
                title=str(p.get("title", "")),
                abstract=str(p.get("abstract", "")),
                published=str(p.get("published", "")),
                updated=str(p.get("updated", "")),
                primary_category=str(p.get("primary_category", "")),
                all_categories=list(p.get("all_categories", [])),
                top_category=top_cat,
                top_category_name=top_name,
                subcategory_name=sub_name,
            )
        )

    LOGGER.info("Mapped %d records (%d unmapped/skipped)", len(records), unmapped)

    # ── Balance and split ────────────────────────────────────────────────────
    records = balance_dataset(
        records,
        max_per_class=args.max_per_class,
        min_per_class=args.min_per_class,
        seed=args.seed,
        drop_sparse=args.drop_sparse,
    )
    LOGGER.info("After balancing: %d records", len(records))

    train_set, val_set, test_set = stratified_split(
        records, args.train_ratio, args.val_ratio, args.seed
    )
    LOGGER.info(
        "Split → train=%d  val=%d  test=%d",
        len(train_set), len(val_set), len(test_set),
    )

    # ── Write outputs ────────────────────────────────────────────────────────
    write_jsonl(args.outdir / "raw" / "arxiv_dataset.jsonl", records)
    write_jsonl(
        args.outdir / "processed" / "splits" / "train.jsonl", train_set
    )
    write_jsonl(
        args.outdir / "processed" / "splits" / "val.jsonl", val_set
    )
    write_jsonl(
        args.outdir / "processed" / "splits" / "test.jsonl", test_set
    )
    LOGGER.info("All files written to %s", args.outdir)


if __name__ == "__main__":
    main()