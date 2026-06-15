"""
count_per_category.py
---------------------
Numără articole (sau fragmente) per categorie din fișierele JSONL ale corpusului.

Utilizare:
    # Pe fișierul de articole (un rând = un articol):
    python count_per_category.py --input arxiv_dataset.jsonl

    # Pe fișierul de fragmente (un rând = un fragment):
    python count_per_category.py --input chunked_database.jsonl --mode chunks

    # Numărare după subcategorie în loc de categoria principală:
    python count_per_category.py --input arxiv_dataset.jsonl --field primary_category

    # Salvează și rezultatele într-un fișier CSV:
    python count_per_category.py --input arxiv_dataset.jsonl --csv rezultate.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Citire JSONL cu progres
# ---------------------------------------------------------------------------

def iter_jsonl(path: Path):
    """Generator care citește linie cu linie dintr-un fișier JSONL."""
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [!] Linia {i} invalidă, ignorată: {e}", file=sys.stderr)


def top_category(primary: str) -> str:
    """Extrage categoria principală dintr-un cod de subcategorie (ex: 'cs.AI' -> 'cs')."""
    return primary.split(".")[0] if primary else "necunoscut"


# ---------------------------------------------------------------------------
# Numărare articole unice per categorie
# ---------------------------------------------------------------------------

def count_papers(path: Path, field: str) -> tuple[Counter, int]:
    """
    Numără articole unice per valoare a câmpului `field`.
    Un articol poate apărea de mai multe ori în chunked_database — deduplicăm după arxiv_id.
    """
    seen_ids: set[str] = set()
    counts: Counter = Counter()
    total = 0

    for record in iter_jsonl(path):
        arxiv_id = str(record.get("arxiv_id", ""))
        if arxiv_id in seen_ids:
            continue
        seen_ids.add(arxiv_id)
        total += 1

        value = str(record.get(field, "necunoscut")).strip()
        if not value:
            value = "necunoscut"

        counts[value] += 1

        if total % 50_000 == 0:
            print(f"  ... {total:,} articole procesate", file=sys.stderr)

    return counts, total


# ---------------------------------------------------------------------------
# Numărare fragmente per categorie (fără deduplicare)
# ---------------------------------------------------------------------------

def count_chunks(path: Path, field: str) -> tuple[Counter, int]:
    """Numără toate fragmentele (rândurile) per valoare a câmpului `field`."""
    counts: Counter = Counter()
    total = 0

    for record in iter_jsonl(path):
        total += 1
        value = str(record.get(field, "necunoscut")).strip()
        if not value:
            value = "necunoscut"
        counts[value] += 1

        if total % 100_000 == 0:
            print(f"  ... {total:,} fragmente procesate", file=sys.stderr)

    return counts, total


# ---------------------------------------------------------------------------
# Afișare tabel
# ---------------------------------------------------------------------------

def print_table(counts: Counter, total: int, label_col: str, count_label: str) -> None:
    """Afișează rezultatele sortate descrescător."""
    max_cat_len = max((len(k) for k in counts), default=10)
    col_w = max(max_cat_len, len(label_col))

    header = f"{'#':<4}  {label_col:<{col_w}}  {count_label:>10}  {'%':>7}"
    print("\n" + "=" * len(header))
    print(header)
    print("-" * len(header))

    for rank, (cat, count) in enumerate(counts.most_common(), 1):
        pct = count / total * 100 if total else 0
        print(f"{rank:<4}  {cat:<{col_w}}  {count:>10,}  {pct:>6.2f}%")

    print("=" * len(header))
    print(f"{'TOTAL':<4}  {'':>{col_w}}  {total:>10,}  {'100.00%':>7}")
    print()


# ---------------------------------------------------------------------------
# Export CSV
# ---------------------------------------------------------------------------

def save_csv(counts: Counter, total: int, csv_path: Path, count_label: str) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "categorie", count_label, "procent"])
        for rank, (cat, count) in enumerate(counts.most_common(), 1):
            pct = round(count / total * 100, 4) if total else 0
            writer.writerow([rank, cat, count, pct])
    print(f"Rezultatele au fost salvate în: {csv_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Numără articole sau fragmente per categorie din fișierele JSONL ale corpusului.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path("arxiv_dataset.jsonl"),
        help="Calea către fișierul JSONL (implicit: arxiv_dataset.jsonl)",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["papers", "chunks"],
        default="papers",
        help=(
            "papers = numără articole unice (deduplicat după arxiv_id) — "
            "potrivit pentru arxiv_dataset.jsonl; "
            "chunks = numără toate fragmentele — potrivit pentru chunked_database.jsonl "
            "(implicit: papers)"
        ),
    )
    parser.add_argument(
        "--field", "-f",
        default="top_category",
        help=(
            "Câmpul JSON după care se grupează. "
            "Valori frecvente: top_category, primary_category. "
            "(implicit: top_category)"
        ),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Dacă este specificat, salvează rezultatele și într-un fișier CSV.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Eroare: fișierul '{args.input}' nu a fost găsit.", file=sys.stderr)
        sys.exit(1)

    print(f"\nFișier:  {args.input}")
    print(f"Mod:     {args.mode}")
    print(f"Câmp:    {args.field}")
    print("Se procesează...\n")

    if args.mode == "papers":
        counts, total = count_papers(args.input, args.field)
        count_label = "articole"
    else:
        counts, total = count_chunks(args.input, args.field)
        count_label = "fragmente"

    print_table(counts, total, label_col=args.field, count_label=count_label)

    if args.csv:
        save_csv(counts, total, args.csv, count_label)


if __name__ == "__main__":
    main()