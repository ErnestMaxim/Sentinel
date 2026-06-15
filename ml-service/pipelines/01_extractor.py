"""
01_extractor.py — large-scale arXiv dataset collector (v2).

Changes vs previous version:
  1. CATEGORY_TARGETS updated based on real corpus analysis.
     Sparse categories (cs, eess, stat, q-bio, q-fin, nlin) now have
     much higher targets to close the gap with physics-heavy categories.

  2. --max-per-class default raised to 20_000
     The old default of 2_000 was silently capping all categories
     regardless of how much the API returned.

  3. New --categories flag to fetch only specific categories.
     Lets you top up individual sparse categories without re-fetching
     everything.

  4. Sort order alternates between submittedDate and lastUpdatedDate
     to maximise temporal diversity within each category.

  5. Better duplicate detection — arxiv_id normalisation strips version
     suffixes (2511.05984v1 → 2511.05984) before deduplication.

Category targets rationale
---------------------------
Current corpus (vectors):     Target (papers):
  astro-ph  215,849  good    →  keep 6,000
  quant-ph  186,996  good    →  keep 5,000
  hep-ph    179,041  good    →  keep 4,000
  hep-th    173,292  good    →  keep 4,000
  gr-qc     117,742  ok      →  keep 3,000
  math       60,736  thin    →  raise to 8,000
  nucl-th    55,188  thin    →  raise to 6,000
  math-ph    44,681  thin    →  raise to 5,000
  physics    39,209  thin    →  raise to 8,000
  cond-mat   32,003  thin    →  raise to 8,000
  hep-ex     31,637  thin    →  raise to 3,000
  hep-lat    31,302  thin    →  keep 2,000
  nucl-ex    24,136  sparse  →  raise to 3,000
  nlin        3,920  sparse  →  raise to 5,000
  cs          7,727  sparse  →  raise to 20,000  ← biggest gap
  eess          712  critical→  raise to 8,000
  stat          490  critical→  raise to 8,000
  q-bio         485  critical→  raise to 5,000
  q-fin          29  critical→  raise to 5,000
"""
from __future__ import annotations

import argparse
import json
import logging
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

# ---------------------------------------------------------------------------
# Per-category fetch targets
# Targets are in PAPERS (not chunks). Each paper becomes ~15–30 chunks.
# ---------------------------------------------------------------------------

CATEGORY_TARGETS: dict[str, int] = {
    # Critical — nearly empty, fetch as many as arXiv has
    "cs":       20_000,   # was 10_000 in old version, corpus has only 7,727 vectors
    "eess":      8_000,   # was 3_000, corpus has only 712 vectors
    "stat":      8_000,   # was 5_000, corpus has only 490 vectors
    "q-bio":     5_000,   # was 2_000, corpus has only 485 vectors
    "q-fin":     5_000,   # was 2_000, corpus has only 29 vectors
    "nlin":      5_000,   # was 2_000, corpus has only 3,920 vectors
    "econ":      5_000,   # not in corpus at all

    # Sparse — significantly underrepresented
    "cond-mat":  8_000,   # was 6_000, corpus has only 32,003 vectors
    "physics":   8_000,   # was 8,000, corpus has 39,209 vectors — keep
    "math":      8_000,   # corpus has 60,736 — keep
    "nucl-th":   6_000,   # corpus has 55,188 — slight boost
    "math-ph":   5_000,   # corpus has 44,681 — keep
    "nucl-ex":   3_000,   # corpus has 24,136 — boost
    "hep-ex":    3_000,   # corpus has 31,637 — keep
    "hep-lat":   2_000,   # corpus has 31,302 — keep

    # Good — already well represented, maintain
    "astro-ph":  6_000,
    "quant-ph":  5_000,
    "hep-ph":    4_000,
    "hep-th":    4_000,
    "gr-qc":     3_000,
}

DEFAULT_TARGET = 500   # fallback for any unlisted category


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

def load_hierarchy(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_label_maps(
    hierarchy: dict,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """
    Returns:
      sub_to_top  : subcategory code → top-level code  (e.g. "cs.AI" → "cs")
      top_to_name : top-level code   → human name      (e.g. "cs" → "Computer Science")
      sub_to_name : subcategory code → human name      (e.g. "cs.AI" → "Artificial Intelligence")
    """
    sub_to_top: dict[str, str] = {}
    top_to_name: dict[str, str] = {}
    sub_to_name: dict[str, str] = {}

    for top_code, top_data in hierarchy.items():
        top_to_name[top_code] = top_data.get("name", top_code)
        sub_to_top[top_code] = top_code  # top-level maps to itself
        sub_to_name[top_code] = top_data.get("name", top_code)

        for sub_code, sub_name in top_data.get("subcategories", {}).items():
            sub_to_top[sub_code] = top_code
            sub_to_name[sub_code] = sub_name

    return sub_to_top, top_to_name, sub_to_name


def map_labels(
    primary_category: str,
    all_categories: list[str],
    sub_to_top: dict[str, str],
    top_to_name: dict[str, str],
    sub_to_name: dict[str, str],
) -> tuple[str, str, str] | None:
    """
    Map a paper's categories to (top_code, top_name, sub_name).
    Returns None if no mapping found.
    """
    for cat in [primary_category] + all_categories:
        top = sub_to_top.get(cat)
        if top:
            return top, top_to_name[top], sub_to_name.get(cat, cat)
    return None


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------

def normalise_arxiv_id(raw_id: str) -> str:
    """Strip version suffix: '2511.05984v1' → '2511.05984'."""
    base = raw_id.rsplit("/", 1)[-1]   # remove URL prefix if present
    # Remove version suffix vN
    if "v" in base:
        base = base.rsplit("v", 1)[0]
    return base.strip()


def parse_entry(entry: ET.Element) -> dict[str, Any]:
    id_text = entry.findtext("atom:id", default="", namespaces=ATOM_NS).strip()
    arxiv_id = normalise_arxiv_id(id_text) if id_text else ""

    title = " ".join(
        entry.findtext("atom:title", default="", namespaces=ATOM_NS).split()
    )
    abstract = " ".join(
        entry.findtext("atom:summary", default="", namespaces=ATOM_NS).split()
    )
    published = entry.findtext("atom:published", default="", namespaces=ATOM_NS).strip()
    updated   = entry.findtext("atom:updated",   default="", namespaces=ATOM_NS).strip()

    primary_el = entry.find("arxiv:primary_category", namespaces=ATOM_NS)
    primary_category = (
        primary_el.attrib.get("term", "").strip() if primary_el is not None else ""
    )

    all_categories: list[str] = []
    for c in entry.findall("atom:category", namespaces=ATOM_NS):
        term = c.attrib.get("term", "").strip()
        if term:
            all_categories.append(term)

    return {
        "arxiv_id":        arxiv_id,
        "title":           title,
        "abstract":        abstract,
        "published":       published,
        "updated":         updated,
        "primary_category": primary_category,
        "all_categories":  list(dict.fromkeys(all_categories)),
    }


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_top_category(
    session: requests.Session,
    top_cat: str,
    target: int,
    batch_size: int,
    pause_sec: float,
    seen_ids: set[str],
    start_offset: int = 0,
    hierarchy: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch up to `target` unique papers for a top-level arXiv category.

    arXiv's API broke sortBy for top-level category codes (cat:cs returns 0
    results when sortBy is set). Fix: query each subcategory individually
    without sortBy, which works correctly. Falls back to the top-level code
    for categories that have no subcategories in the hierarchy.

    Parameters
    ----------
    start_offset : ignored — kept for API compatibility. Subcategory strategy
                   doesn't need offset tracking since each subcategory is
                   fetched independently and deduplication handles overlaps.
    hierarchy    : the full hierarchy dict for subcategory lookup.
    """
    results: list[dict[str, Any]] = []

    # Build list of query strings to try
    # For categories with subcategories, query each subcategory individually
    subcats: list[str] = []
    if hierarchy and top_cat in hierarchy:
        subcats = list(hierarchy[top_cat].get("subcategories", {}).keys())

    # If no subcategories defined (e.g. hep-lat, nucl-th), query top-level directly
    # These categories work fine with the top-level code
    if not subcats:
        subcats = [top_cat]

    # Distribute target evenly across subcategories
    # Each subcategory gets a proportional share, minimum 50
    per_subcat = max(50, target // len(subcats) + 1)

    LOGGER.info(
        "[%s] Fetching via %d subcategories, ~%d papers each",
        top_cat, len(subcats), per_subcat,
    )

    for subcat in subcats:
        if len(results) >= target:
            break

        remaining_for_subcat = min(per_subcat, target - len(results))
        subcat_results: list[dict[str, Any]] = []
        start = 0
        consecutive_empty = 0

        while len(subcat_results) < remaining_for_subcat:
            n = min(batch_size, remaining_for_subcat - len(subcat_results) + 10)
            params = {
                "search_query": f"cat:{subcat}",
                "start":        start,
                "max_results":  n,
                # NO sortBy — arXiv API returns 0 results for top-level
                # category codes when sortBy is set (confirmed bug May 2026)
            }

            try:
                resp = session.get(ARXIV_API_URL, params=params, timeout=60)
                resp.raise_for_status()
                consecutive_empty = 0
            except requests.RequestException as e:
                LOGGER.warning("[%s/%s] Request failed at offset %d: %s", top_cat, subcat, start, e)
                time.sleep(pause_sec * 3)
                consecutive_empty += 1
                if consecutive_empty >= 5:
                    LOGGER.error("[%s/%s] 5 consecutive failures — skipping subcategory.", top_cat, subcat)
                    break
                continue

            root = ET.fromstring(resp.text)
            entries = root.findall("atom:entry", namespaces=ATOM_NS)

            # Check totalResults to detect API block early
            total_str = root.findtext(
                "{http://a9.com/-/spec/opensearch/1.1/}totalResults", default="?"
            )
            if total_str == "0" and start == 0:
                LOGGER.warning(
                    "[%s/%s] API returned totalResults=0 — possible rate limit. "
                    "Skipping subcategory.",
                    top_cat, subcat,
                )
                break

            if not entries:
                LOGGER.info("[%s/%s] No more entries at offset %d.", top_cat, subcat, start)
                break

            new_count = 0
            for e in entries:
                parsed = parse_entry(e)
                pid = parsed.get("arxiv_id", "").strip()
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    subcat_results.append(parsed)
                    new_count += 1

            LOGGER.info(
                "[%s/%s] offset=%d  fetched=%d  new=%d  subcat_total=%d / %d",
                top_cat, subcat, start, len(entries), new_count,
                len(subcat_results), remaining_for_subcat,
            )

            start += len(entries)

            if len(entries) < batch_size:
                LOGGER.info("[%s/%s] Subcategory exhausted.", top_cat, subcat)
                break

            time.sleep(pause_sec)

        results.extend(subcat_results)
        LOGGER.info(
            "[%s/%s] Done — %d papers. Running total: %d / %d",
            top_cat, subcat, len(subcat_results), len(results), target,
        )

    return results[:target]


# ---------------------------------------------------------------------------
# Checkpoint helpers
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
    """Return set of top categories already fully fetched."""
    marker = path.with_suffix(".completed.json")
    if not marker.exists():
        return set()
    with marker.open("r") as f:
        data = json.load(f)
    # Support both old format (list) and new format (dict with offsets)
    if isinstance(data, list):
        return set(data)
    return set(data.keys())


def save_completed_category(path: Path, top_cat: str, api_offset: int = 0) -> None:
    """
    Mark a category as completed and store the final API offset reached.
    The offset is used on resume to skip past already-fetched pages.
    """
    marker = path.with_suffix(".completed.json")
    existing: dict[str, int] = {}
    if marker.exists():
        with marker.open("r") as f:
            data = json.load(f)
        if isinstance(data, list):
            existing = {cat: 0 for cat in data}
        else:
            existing = data
    existing[top_cat] = api_offset
    with marker.open("w") as f:
        json.dump(existing, f, indent=2)


def load_category_offset(path: Path, top_cat: str) -> int:
    """Return the API offset where we left off for a given category (0 if unknown)."""
    marker = path.with_suffix(".completed.json")
    if not marker.exists():
        return 0
    with marker.open("r") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get(top_cat, 0)
    return 0


# ---------------------------------------------------------------------------
# Dataset balancing and splitting
# ---------------------------------------------------------------------------

def balance_dataset(
    records: list[PaperRecord],
    max_per_class: int,
    min_per_class: int,
    seed: int,
    drop_sparse: bool,
) -> list[PaperRecord]:
    """
    Cap each category at max_per_class.
    When drop_sparse=True, also remove categories below min_per_class.
    """
    import random
    rng = random.Random(seed)

    by_class: dict[str, list[PaperRecord]] = defaultdict(list)
    for r in records:
        by_class[r.top_category].append(r)

    balanced: list[PaperRecord] = []
    for cls, items in sorted(by_class.items()):
        if drop_sparse and len(items) < min_per_class:
            LOGGER.warning(
                "Dropping class '%s' — only %d records (min=%d)",
                cls, len(items), min_per_class,
            )
            continue
        if len(items) > max_per_class:
            items = rng.sample(items, max_per_class)
            LOGGER.info("Capped '%s' at %d records", cls, max_per_class)
        else:
            LOGGER.info("Kept '%s' — %d records", cls, len(items))
        balanced.extend(items)

    rng.shuffle(balanced)
    return balanced


def stratified_split(
    records: list[PaperRecord],
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> tuple[list[PaperRecord], list[PaperRecord], list[PaperRecord]]:
    import random
    rng = random.Random(seed)

    by_class: dict[str, list[PaperRecord]] = defaultdict(list)
    for r in records:
        by_class[r.top_category].append(r)

    train_set: list[PaperRecord] = []
    val_set:   list[PaperRecord] = []
    test_set:  list[PaperRecord] = []

    for items in by_class.values():
        rng.shuffle(items)
        n = len(items)
        n_train = max(1, int(n * train_ratio))
        n_val   = max(1, int(n * val_ratio))
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
        "--outdir", type=Path,
        default=Path("backend/core/antiplagiator/data"),
    )
    parser.add_argument(
        "--batch-size", type=int, default=100,
        help="API results per request (arXiv max = 100)",
    )
    parser.add_argument(
        "--pause-sec", type=float, default=3.0,
        help="Pause between API calls. Be polite — arXiv rate-limits at ~3 req/s",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-per-class", type=int, default=20_000,
        help="Hard cap per category in the balanced output (default: 20,000)"
    )
    parser.add_argument(
        "--min-per-class", type=int, default=50,
        help="Min records to keep a class (only used with --drop-sparse)",
    )
    parser.add_argument(
        "--drop-sparse", action="store_true",
        help="Drop categories below --min-per-class (default: keep all)",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio",   type=float, default=0.1)
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from checkpoint if available",
    )
    parser.add_argument(
        "--categories", type=str, default=None,
        help=(
            "Comma-separated list of top-level category codes to fetch. "
            "Use this to top up specific sparse categories without refetching everything. "
            "Example: --categories cs,eess,stat,q-bio,q-fin"
        ),
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

    # ── Resume or start fresh ─────────────────────────────────────────────
    all_raw: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if args.resume:
        all_raw = load_checkpoint(checkpoint_path)
        seen_ids = {normalise_arxiv_id(str(r.get("arxiv_id", ""))) for r in all_raw}
        LOGGER.info("Resumed with %d seen IDs", len(seen_ids))

    completed_cats = load_completed_categories(checkpoint_path) if args.resume else set()

    # ── Determine which categories to fetch ──────────────────────────────
    if args.categories:
        fetch_cats = [c.strip() for c in args.categories.split(",") if c.strip()]
        LOGGER.info("Fetching only specified categories: %s", fetch_cats)
    else:
        fetch_cats = sorted(CATEGORY_TARGETS.keys())

    # ── Fetch per top category ────────────────────────────────────────────
    for top_cat in fetch_cats:
        if top_cat in completed_cats:
            LOGGER.info("[%s] Already completed, skipping.", top_cat)
            continue

        target = CATEGORY_TARGETS.get(top_cat, DEFAULT_TARGET)

        # Count how many papers we already have for this category
        already_have = sum(
            1 for r in all_raw
            if str(r.get("primary_category", "")).split(".")[0] == top_cat
        )
        remaining = max(0, target - already_have)

        if remaining == 0:
            LOGGER.info(
                "[%s] Already have %d >= target %d — marking complete.",
                top_cat, already_have, target,
            )
            save_completed_category(checkpoint_path, top_cat, api_offset=0)
            completed_cats.add(top_cat)
            continue

        # Resume from the offset where we left off for this category
        start_offset = load_category_offset(checkpoint_path, top_cat) if args.resume else 0

        LOGGER.info(
            "[%s] %s — have=%d  target=%d  need=%d more  start_offset=%d",
            top_cat,
            top_to_name.get(top_cat, top_cat),
            already_have,
            target,
            remaining,
            start_offset,
        )

        papers = fetch_top_category(
            session=session,
            top_cat=top_cat,
            target=remaining,
            batch_size=args.batch_size,
            pause_sec=args.pause_sec,
            seen_ids=seen_ids,
            start_offset=start_offset,
            hierarchy=hierarchy,
        )

        all_raw.extend(papers)

        # Save offset = start_offset + estimated pages fetched
        # This lets a future resume skip past pages we just processed
        new_offset = start_offset + len(papers) + (len(papers) // args.batch_size) * 20
        save_checkpoint(checkpoint_path, all_raw)
        save_completed_category(checkpoint_path, top_cat, api_offset=new_offset)
        completed_cats.add(top_cat)

        LOGGER.info(
            "[%s] Done. Got %d new papers (had %d, now %d total for category). "
            "Checkpoint: %d total records.",
            top_cat, len(papers), already_have, already_have + len(papers), len(all_raw),
        )

    LOGGER.info("Total raw records fetched: %d", len(all_raw))

    # ── Map to PaperRecord ────────────────────────────────────────────────
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
        records.append(PaperRecord(
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
        ))

    LOGGER.info("Mapped %d records (%d unmapped/skipped)", len(records), unmapped)

    # ── Balance and split ─────────────────────────────────────────────────
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

    # ── Write outputs ─────────────────────────────────────────────────────
    write_jsonl(args.outdir / "raw" / "arxiv_dataset.jsonl", records)
    write_jsonl(args.outdir / "processed" / "splits" / "train.jsonl", train_set)
    write_jsonl(args.outdir / "processed" / "splits" / "val.jsonl",   val_set)
    write_jsonl(args.outdir / "processed" / "splits" / "test.jsonl",  test_set)
    LOGGER.info("All files written to %s", args.outdir)


if __name__ == "__main__":
    main()