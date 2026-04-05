from __future__ import annotations

import argparse
import json
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


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


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


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "SentinelDatasetExtractor/1.0"})
    return session


def load_hierarchy(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_label_maps(hierarchy: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
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


def parse_entry(entry: ET.Element) -> dict[str, Any]:
    id_text = entry.findtext("atom:id", default="", namespaces=ATOM_NS).strip()
    arxiv_id = id_text.rsplit("/", 1)[-1] if id_text else ""

    title = " ".join(entry.findtext("atom:title", default="", namespaces=ATOM_NS).split())
    abstract = " ".join(entry.findtext("atom:summary", default="", namespaces=ATOM_NS).split())
    published = entry.findtext("atom:published", default="", namespaces=ATOM_NS).strip()
    updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS).strip()

    primary_el = entry.find("arxiv:primary_category", namespaces=ATOM_NS)
    primary_category = primary_el.attrib.get("term", "").strip() if primary_el is not None else ""

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


def map_labels(
    primary_category: str,
    all_categories: list[str],
    sub_to_top: dict[str, str],
    top_to_name: dict[str, str],
    sub_to_name: dict[str, str],
) -> tuple[str, str, str] | None:
    if primary_category in sub_to_top:
        top = sub_to_top[primary_category]
        return top, top_to_name.get(top, top), sub_to_name.get(primary_category, top_to_name.get(top, top))

    for cat in all_categories:
        if cat in sub_to_top:
            top = sub_to_top[cat]
            return top, top_to_name.get(top, top), sub_to_name.get(cat, top_to_name.get(top, top))
    return None


def fetch_category(
    session: requests.Session,
    cat: str,
    per_category: int,
    batch_size: int,
    pause_sec: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    start = 0

    while start < per_category:
        n = min(batch_size, per_category - start)
        params = {
            "search_query": f"cat:{cat}",
            "start": start,
            "max_results": n,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        resp = session.get(ARXIV_API_URL, params=params, timeout=60)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", namespaces=ATOM_NS)
        if not entries:
            break

        results.extend(parse_entry(e) for e in entries)
        start += len(entries)

        if len(entries) < n:
            break
        time.sleep(pause_sec)

    return results


def balance_dataset(records: list[PaperRecord], max_per_class: int, min_per_class: int, seed: int) -> list[PaperRecord]:
    rng = random.Random(seed)
    by_label: dict[str, list[PaperRecord]] = defaultdict(list)
    for r in records:
        by_label[r.top_category_name].append(r)

    balanced: list[PaperRecord] = []
    for label, items in sorted(by_label.items()):
        if len(items) < min_per_class:
            continue
        rng.shuffle(items)
        selected = items[:max_per_class]
        balanced.extend(selected)

    return balanced


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
        val_set.extend(items[n_train : n_train + n_val])
        test_set.extend(items[n_train + n_val :])

    rng.shuffle(train_set)
    rng.shuffle(val_set)
    rng.shuffle(test_set)
    return train_set, val_set, test_set


def write_jsonl(path: Path, records: list[PaperRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build arXiv dataset for category classification")
    parser.add_argument("--hierarchy", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, default=Path("backend/core/antiplagiator/data"))
    parser.add_argument("--per-category", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--pause-sec", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-per-class", type=int, default=100)
    parser.add_argument("--max-per-class", type=int, default=400)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    session = build_session()

    hierarchy = load_hierarchy(args.hierarchy)
    sub_to_top, top_to_name, sub_to_name = build_label_maps(hierarchy)

    target_subcategories = sorted(sub_to_top.keys())
    all_raw: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for i, cat in enumerate(target_subcategories, start=1):
        papers = fetch_category(session, cat, args.per_category, args.batch_size, args.pause_sec)
        for p in papers:
            pid = str(p.get("arxiv_id", "")).strip()
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_raw.append(p)

    records: list[PaperRecord] = []
    for p in all_raw:
        mapped = map_labels(
            str(p.get("primary_category", "")),
            list(p.get("all_categories", [])),
            sub_to_top,
            top_to_name,
            sub_to_name,
        )
        if mapped is None:
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

    records = balance_dataset(records, args.max_per_class, args.min_per_class, args.seed)
    train_set, val_set, test_set = stratified_split(records, args.train_ratio, args.val_ratio, args.seed)

    write_jsonl(args.outdir / "raw" / "arxiv_dataset.jsonl", records)
    write_jsonl(args.outdir / "processed" / "splits" / "train.jsonl", train_set)
    write_jsonl(args.outdir / "processed" / "splits" / "val.jsonl", val_set)
    write_jsonl(args.outdir / "processed" / "splits" / "test.jsonl", test_set)


if __name__ == "__main__":
    main()