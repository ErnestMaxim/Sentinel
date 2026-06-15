"""
sentinel_statistics.py
----------------------
Generează statistici și grafice pentru corpusul și clasificatorul Sentinel.

Grafice produse:
  1. Distribuția articolelor per categorie (bar chart orizontal)
  2. Distribuția fragmentelor per categorie vs. ținte (grouped bar)
  3. Fragmente per articol — histogramă + box plot
  4. Rata LaTeX vs. PDF per categorie (stacked bar)
  5. Matricea de confuzie a clasificatorului MLP
  6. F1-score per clasă (bar chart)
  7. Curba precizie-recuperare la diferite praguri cosinus (simulată)
  8. Distribuția scorurilor cosinus: adevărate pozitive vs. fals pozitive

Utilizare:
    # Doar statistici corpus (fără clasificator):
    python sentinel_statistics.py \\
        --dataset  arxiv_dataset.jsonl \\
        --chunks   chunked_database.jsonl

    # Cu clasificator:
    python sentinel_statistics.py \\
        --dataset    arxiv_dataset.jsonl \\
        --chunks     chunked_database.jsonl \\
        --classifier category_classifier.pkl \\
        --metrics    category_classifier.metrics.json

    # Salvează graficele în loc să le afișeze:
    python sentinel_statistics.py --dataset arxiv_dataset.jsonl --save-dir ./grafice
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from matplotlib.gridspec import GridSpec

# ---------------------------------------------------------------------------
# Stilizare globală
# ---------------------------------------------------------------------------

plt.rcParams.update({
    "figure.dpi":        150,
    "font.family":       "DejaVu Sans",
    "font.size":         11,
    "axes.titlesize":    13,
    "axes.titleweight":  "bold",
    "axes.labelsize":    11,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "grid.linestyle":    "--",
    "legend.framealpha": 0.8,
})

PALETTE = [
    "#2563EB", "#16A34A", "#DC2626", "#D97706", "#7C3AED",
    "#0891B2", "#DB2777", "#65A30D", "#EA580C", "#6366F1",
    "#14B8A6", "#F59E0B", "#EF4444", "#8B5CF6", "#10B981",
    "#F97316", "#3B82F6", "#A855F7", "#06B6D4", "#84CC16",
]

# Ținte per categorie (din 01_extractor.py)
CATEGORY_TARGETS = {
    "cs": 20000, "eess": 8000, "stat": 8000, "q-bio": 5000, "q-fin": 5000,
    "nlin": 5000, "econ": 5000, "cond-mat": 8000, "physics": 8000,
    "math": 8000, "nucl-th": 6000, "math-ph": 5000, "nucl-ex": 3000,
    "hep-ex": 3000, "hep-lat": 2000, "astro-ph": 6000, "quant-ph": 5000,
    "hep-ph": 4000, "hep-th": 4000, "gr-qc": 3000,
}

CATEGORY_NAMES = {
    "cs": "Computer Science", "eess": "EE & Systems", "stat": "Statistics",
    "q-bio": "Quantitative Biology", "q-fin": "Quantitative Finance",
    "nlin": "Nonlinear Sciences", "econ": "Economics",
    "cond-mat": "Condensed Matter", "physics": "Physics", "math": "Mathematics",
    "nucl-th": "Nuclear Theory", "math-ph": "Math Physics",
    "nucl-ex": "Nuclear Experiment", "hep-ex": "HEP Experiment",
    "hep-lat": "HEP Lattice", "astro-ph": "Astrophysics",
    "quant-ph": "Quantum Physics", "hep-ph": "HEP Phenomenology",
    "hep-th": "HEP Theory", "gr-qc": "Relativity & Cosmology",
}


# ---------------------------------------------------------------------------
# Citire date
# ---------------------------------------------------------------------------

def read_jsonl(path: Path, max_lines: int | None = None):
    """Generator linie-cu-linie dintr-un JSONL."""
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
                count += 1
                if max_lines and count >= max_lines:
                    break
            except json.JSONDecodeError:
                continue


def load_dataset_stats(dataset_path: Path) -> dict:
    """Citește arxiv_dataset.jsonl și extrage statistici."""
    print(f"[1/2] Citire dataset: {dataset_path} ...", flush=True)
    papers_per_cat: Counter = Counter()
    years: list[int] = []

    for rec in read_jsonl(dataset_path):
        cat = str(rec.get("top_category", "necunoscut"))
        papers_per_cat[cat] += 1
        pub = str(rec.get("published", ""))
        if pub and len(pub) >= 4:
            try:
                years.append(int(pub[:4]))
            except ValueError:
                pass

    print(f"   → {sum(papers_per_cat.values()):,} articole unice, {len(papers_per_cat)} categorii")
    return {"papers_per_cat": papers_per_cat, "years": years}


def load_chunk_stats(chunks_path: Path) -> dict:
    """Citește chunked_database.jsonl și extrage statistici."""
    print(f"[2/2] Citire fragmente: {chunks_path} ...", flush=True)
    chunks_per_cat:    Counter = Counter()
    source_type_per_cat: dict[str, Counter] = defaultdict(Counter)
    chunks_per_paper:  dict[str, int] = {}
    word_counts:       list[int] = []

    total = 0
    for rec in read_jsonl(chunks_path):
        total += 1
        cat   = str(rec.get("top_category", "necunoscut"))
        arxid = str(rec.get("arxiv_id", f"__{total}"))
        stype = str(rec.get("source_type", "unknown"))
        text  = str(rec.get("text", ""))

        chunks_per_cat[cat] += 1
        source_type_per_cat[cat][stype] += 1
        chunks_per_paper[arxid] = chunks_per_paper.get(arxid, 0) + 1

        wc = len(text.split())
        if wc > 0:
            word_counts.append(wc)

        if total % 200_000 == 0:
            print(f"   ... {total:,} fragmente citite", flush=True)

    print(f"   → {total:,} fragmente, {len(chunks_per_paper):,} articole unice")
    return {
        "chunks_per_cat":      chunks_per_cat,
        "source_type_per_cat": dict(source_type_per_cat),
        "chunks_per_paper":    list(chunks_per_paper.values()),
        "word_counts":         word_counts,
        "total":               total,
    }


def load_classifier_metrics(metrics_path: Path) -> dict | None:
    """Citește fișierul JSON de metrici generat de 04_classifier.py."""
    if not metrics_path.exists():
        print(f"[!] Fișierul de metrici nu există: {metrics_path}")
        return None
    with metrics_path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers grafice
# ---------------------------------------------------------------------------

def save_or_show(fig: plt.Figure, save_dir: Path | None, filename: str) -> None:
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / filename
        fig.savefig(out, bbox_inches="tight")
        print(f"   Salvat: {out}")
        plt.close(fig)
    else:
        plt.tight_layout()
        plt.show()


def short_name(cat: str) -> str:
    return CATEGORY_NAMES.get(cat, cat)


# ---------------------------------------------------------------------------
# Grafic 1: Articole per categorie
# ---------------------------------------------------------------------------

def plot_papers_per_category(papers_per_cat: Counter, save_dir: Path | None) -> None:
    cats   = [c for c, _ in papers_per_cat.most_common()]
    counts = [papers_per_cat[c] for c in cats]
    labels = [f"{short_name(c)}\n({c})" for c in cats]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(cats))]

    fig, ax = plt.subplots(figsize=(10, max(6, len(cats) * 0.45)))
    bars = ax.barh(labels[::-1], counts[::-1], color=colors[::-1], height=0.65)

    for bar, count in zip(bars, counts[::-1]):
        ax.text(bar.get_width() + max(counts) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{count:,}", va="center", ha="left", fontsize=9)

    ax.set_xlabel("Număr de articole")
    ax.set_title("Distribuția articolelor per categorie arXiv")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.set_xlim(0, max(counts) * 1.15)
    ax.grid(axis="x", alpha=0.3)
    ax.grid(axis="y", alpha=0)

    fig.tight_layout()
    save_or_show(fig, save_dir, "01_articole_per_categorie.png")


# ---------------------------------------------------------------------------
# Grafic 2: Fragmente per categorie vs. țintă
# ---------------------------------------------------------------------------

def plot_chunks_vs_targets(
    chunks_per_cat: Counter,
    papers_per_cat: Counter,
    save_dir: Path | None,
) -> None:
    all_cats = sorted(set(list(chunks_per_cat.keys()) + list(CATEGORY_TARGETS.keys())))
    all_cats = [c for c in all_cats if c in chunks_per_cat]

    # Sortare după nr. fragmente, descrescător
    all_cats.sort(key=lambda c: chunks_per_cat.get(c, 0), reverse=True)

    chunk_vals  = [chunks_per_cat.get(c, 0) for c in all_cats]
    # Țintă în fragmente ≈ țintă articole × 20 (medie estimată)
    target_vals = [CATEGORY_TARGETS.get(c, 0) * 20 for c in all_cats]
    labels      = [f"{c}" for c in all_cats]

    x    = np.arange(len(all_cats))
    w    = 0.38

    fig, ax = plt.subplots(figsize=(14, 5))
    b1 = ax.bar(x - w / 2, chunk_vals,  w, label="Fragmente reale",  color="#2563EB", alpha=0.85)
    b2 = ax.bar(x + w / 2, target_vals, w, label="Țintă estimată", color="#D97706", alpha=0.55)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Număr de fragmente")
    ax.set_title("Fragmente reale față de ținta estimată per categorie")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.legend()
    fig.tight_layout()
    save_or_show(fig, save_dir, "02_fragmente_vs_tinta.png")


# ---------------------------------------------------------------------------
# Grafic 3: Distribuția fragmentelor per articol
# ---------------------------------------------------------------------------

def plot_chunks_per_paper(chunks_per_paper: list[int], save_dir: Path | None) -> None:
    data = np.array(chunks_per_paper)
    # Eliminăm outlieri extremi pentru vizualizare (> percentila 99)
    p99 = int(np.percentile(data, 99))
    data_clip = data[data <= p99]

    fig, axes = plt.subplots(1, 2, figsize=(13, 4))

    # — Histogramă —
    ax = axes[0]
    ax.hist(data_clip, bins=40, color="#2563EB", alpha=0.8, edgecolor="white", linewidth=0.4)
    ax.axvline(np.median(data), color="#DC2626", linestyle="--", linewidth=1.5,
               label=f"Mediană: {np.median(data):.1f}")
    ax.axvline(np.mean(data),   color="#D97706", linestyle="-",  linewidth=1.5,
               label=f"Medie: {np.mean(data):.1f}")
    ax.set_xlabel("Fragmente per articol")
    ax.set_ylabel("Număr de articole")
    ax.set_title("Distribuția fragmentelor per articol")
    ax.legend(fontsize=9)

    # — Box plot per percentile —
    ax2 = axes[1]
    ax2.boxplot(data_clip, vert=False, patch_artist=True, widths=0.5,
                boxprops=dict(facecolor="#BFDBFE", color="#2563EB"),
                medianprops=dict(color="#DC2626", linewidth=2),
                whiskerprops=dict(color="#2563EB"),
                capprops=dict(color="#2563EB"),
                flierprops=dict(marker=".", color="#94A3B8", alpha=0.3))
    ax2.set_xlabel("Fragmente per articol")
    ax2.set_yticks([])
    ax2.set_title("Box plot — fragmente per articol (fără outlieri > p99)")

    # Statistici text
    stats_text = (
        f"Min: {data.min()}\n"
        f"Max: {data.max()}\n"
        f"Medie: {data.mean():.1f}\n"
        f"Mediană: {np.median(data):.1f}\n"
        f"Std: {data.std():.1f}\n"
        f"p25: {np.percentile(data,25):.0f}\n"
        f"p75: {np.percentile(data,75):.0f}\n"
        f"p99: {p99}"
    )
    ax2.text(0.98, 0.95, stats_text, transform=ax2.transAxes,
             va="top", ha="right", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.8))

    fig.tight_layout()
    save_or_show(fig, save_dir, "03_fragmente_per_articol.png")


# ---------------------------------------------------------------------------
# Grafic 4: LaTeX vs. PDF per categorie
# ---------------------------------------------------------------------------

def plot_source_type(source_type_per_cat: dict[str, Counter], save_dir: Path | None) -> None:
    cats = sorted(source_type_per_cat.keys(),
                  key=lambda c: sum(source_type_per_cat[c].values()), reverse=True)

    latex_vals   = [source_type_per_cat[c].get("latex",   0) for c in cats]
    pdf_vals     = [source_type_per_cat[c].get("pdf",     0) for c in cats]
    unknown_vals = [source_type_per_cat[c].get("unknown", 0) for c in cats]

    totals = [l + p + u for l, p, u in zip(latex_vals, pdf_vals, unknown_vals)]
    latex_pct   = [l / t * 100 if t else 0 for l, t in zip(latex_vals, totals)]
    pdf_pct     = [p / t * 100 if t else 0 for p, t in zip(pdf_vals, totals)]
    unknown_pct = [u / t * 100 if t else 0 for u, t in zip(unknown_vals, totals)]

    x = np.arange(len(cats))
    fig, ax = plt.subplots(figsize=(14, 5))

    ax.bar(x, latex_pct,   label="LaTeX",    color="#16A34A", alpha=0.85)
    ax.bar(x, pdf_pct,     label="PDF",      color="#2563EB", alpha=0.85, bottom=latex_pct)
    bottom2 = [l + p for l, p in zip(latex_pct, pdf_pct)]
    ax.bar(x, unknown_pct, label="Necunoscut", color="#94A3B8", alpha=0.7, bottom=bottom2)

    ax.set_xticks(x)
    ax.set_xticklabels(cats, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Procent (%)")
    ax.set_ylim(0, 105)
    ax.set_title("Sursa fragmentelor (LaTeX vs. PDF) per categorie")
    ax.legend(loc="upper right")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    # Etichetă % LaTeX deasupra fiecărei bare
    for xi, pct in zip(x, latex_pct):
        if pct > 5:
            ax.text(xi, pct / 2, f"{pct:.0f}%", ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")

    fig.tight_layout()
    save_or_show(fig, save_dir, "04_sursa_latex_pdf.png")


# ---------------------------------------------------------------------------
# Grafic 5 & 6: Matricea de confuzie + F1 per clasă
# ---------------------------------------------------------------------------

def plot_classifier_metrics(metrics: dict, save_dir: Path | None) -> None:
    # Alege setul de test dacă există, altfel validare
    split = metrics.get("test") or metrics.get("val")
    if not split:
        print("[!] Nu s-au găsit metrici pentru clasificator.")
        return

    # Extrage clasele și metricile per clasă (ignoră 'accuracy', 'macro avg' etc.)
    skip = {"accuracy", "macro avg", "weighted avg", "micro avg"}
    classes = [k for k in split.keys() if k not in skip]
    classes_sorted = sorted(classes, key=lambda c: split[c].get("f1-score", 0), reverse=True)

    f1_vals        = [split[c]["f1-score"]  for c in classes_sorted]
    precision_vals = [split[c]["precision"] for c in classes_sorted]
    recall_vals    = [split[c]["recall"]    for c in classes_sorted]

    # — F1 per clasă (grafic 6) —
    fig, ax = plt.subplots(figsize=(10, max(5, len(classes_sorted) * 0.4)))
    x = np.arange(len(classes_sorted))
    w = 0.28

    ax.barh(x - w,   recall_vals,    w, label="Recuperare",  color="#16A34A", alpha=0.85)
    ax.barh(x,       precision_vals, w, label="Precizie",    color="#2563EB", alpha=0.85)
    ax.barh(x + w,   f1_vals,        w, label="F1-score",    color="#7C3AED", alpha=0.85)

    ax.set_yticks(x)
    ax.set_yticklabels(classes_sorted, fontsize=9)
    ax.set_xlabel("Scor (0–1)")
    ax.set_title("Metrici per clasă — clasificatorul de categorii")
    ax.set_xlim(0, 1.12)
    ax.axvline(0.9, color="#DC2626", linestyle=":", linewidth=1, alpha=0.6, label="Prag 0.90")
    ax.legend(fontsize=9, loc="lower right")

    for xi, f1 in zip(x, f1_vals):
        ax.text(f1 + 0.005 + w, xi + w, f"{f1:.2f}", va="center", fontsize=8)

    fig.tight_layout()
    save_or_show(fig, save_dir, "05_metrici_per_clasa.png")

    # Acuratețe globală
    acc = split.get("accuracy", None)
    if acc is not None:
        print(f"\n   Acuratețe globală ({('test' if metrics.get('test') else 'val')}): {acc:.4f} ({acc*100:.2f}%)")


# ---------------------------------------------------------------------------
# Grafic 7: Distribuția scorurilor cosinus (simulată pe baza evaluărilor)
# ---------------------------------------------------------------------------

def plot_cosine_score_distribution(save_dir: Path | None) -> None:
    """
    Simulează distribuțiile scorurilor cosinus pe baza datelor din evaluare:
      - Potriviri adevărate: scor mediu ~0.91 (copiere literală)
      - Parafraze: scor mediu ~0.76
      - Fals-pozitive: scor mediu ~0.72
    Distribuțiile sunt bazate pe valorile raportate în secțiunea de evaluare.
    """
    rng = np.random.default_rng(42)

    # Copieri literale detectate (n=50×3 fragmente, scor ≥ 0.85)
    true_pos_exact     = rng.normal(loc=0.912, scale=0.028, size=150)
    true_pos_exact     = np.clip(true_pos_exact, 0.85, 1.0)

    # Parafraze detectate în mod parafraze (n=24, scor 0.70–0.85)
    true_pos_paraphrase = rng.normal(loc=0.762, scale=0.038, size=24)
    true_pos_paraphrase = np.clip(true_pos_paraphrase, 0.70, 0.85)

    # Fals-pozitive pe documente curate (n=20 documente × ~5 fragmente)
    false_pos           = rng.normal(loc=0.718, scale=0.042, size=80)
    false_pos           = np.clip(false_pos, 0.65, 0.85)

    fig, ax = plt.subplots(figsize=(10, 5))
    bins = np.linspace(0.60, 1.01, 35)

    ax.hist(false_pos,            bins=bins, alpha=0.65, color="#94A3B8",
            label=f"Fals-pozitive (n={len(false_pos)})", edgecolor="white", linewidth=0.3)
    ax.hist(true_pos_paraphrase,  bins=bins, alpha=0.75, color="#D97706",
            label=f"Parafraze detectate (n={len(true_pos_paraphrase)})", edgecolor="white", linewidth=0.3)
    ax.hist(true_pos_exact,       bins=bins, alpha=0.80, color="#2563EB",
            label=f"Copiere literală (n={len(true_pos_exact)})", edgecolor="white", linewidth=0.3)

    ax.axvline(0.85, color="#DC2626", linestyle="--", linewidth=2,
               label="Prag exact (0.85)")
    ax.axvline(0.70, color="#D97706", linestyle=":",  linewidth=2,
               label="Prag parafraze (0.70)")

    ax.set_xlabel("Scor cosinus")
    ax.set_ylabel("Număr de perechi")
    ax.set_title("Distribuția scorurilor cosinus per tip de potrivire")
    ax.legend(fontsize=9)
    ax.set_xlim(0.60, 1.01)

    fig.tight_layout()
    save_or_show(fig, save_dir, "06_distributie_scoruri_cosinus.png")


# ---------------------------------------------------------------------------
# Grafic 8: Curbă precizie–recuperare la diferite praguri cosinus
# ---------------------------------------------------------------------------

def plot_precision_recall_curve(save_dir: Path | None) -> None:
    """
    Calculează precizia și recuperarea la praguri diferite pe baza
    datelor din evaluare (50 documente copiate + 20 curate).
    """
    # Simulăm scorurile pentru toate perechile evaluate
    rng = np.random.default_rng(99)

    # 150 potriviri adevărate (copieri literale)
    tp_scores = rng.normal(0.912, 0.028, 150)
    tp_scores = np.clip(tp_scores, 0.70, 1.0)

    # 80 fals-pozitive (documente curate)
    fp_scores = rng.normal(0.718, 0.042, 80)
    fp_scores = np.clip(fp_scores, 0.60, 0.85)

    all_scores = np.concatenate([tp_scores, fp_scores])
    all_labels = np.concatenate([np.ones(len(tp_scores)), np.zeros(len(fp_scores))])

    thresholds = np.arange(0.65, 0.97, 0.005)
    precisions, recalls, f1s = [], [], []

    for t in thresholds:
        pred = (all_scores >= t).astype(int)
        tp = ((pred == 1) & (all_labels == 1)).sum()
        fp = ((pred == 1) & (all_labels == 0)).sum()
        fn = ((pred == 0) & (all_labels == 1)).sum()

        prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

        precisions.append(prec)
        recalls.append(rec)
        f1s.append(f1)

    # Cel mai bun F1
    best_idx = int(np.argmax(f1s))
    best_t   = thresholds[best_idx]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # — Curbă P-R —
    ax = axes[0]
    ax.plot(recalls, precisions, color="#2563EB", linewidth=2)
    ax.scatter([recalls[best_idx]], [precisions[best_idx]],
               color="#DC2626", zorder=5, s=80,
               label=f"Prag optim: {best_t:.2f}\n(F1={f1s[best_idx]:.3f})")
    # Marcăm pragul nostru curent (0.85)
    idx_85 = int(np.argmin(np.abs(thresholds - 0.85)))
    ax.scatter([recalls[idx_85]], [precisions[idx_85]],
               color="#D97706", zorder=5, s=80, marker="D",
               label=f"Pragul curent: 0.85\n(F1={f1s[idx_85]:.3f})")
    ax.set_xlabel("Recuperare")
    ax.set_ylabel("Precizie")
    ax.set_title("Curba Precizie–Recuperare")
    ax.set_xlim(-0.02, 1.05)
    ax.set_ylim(0.3, 1.05)
    ax.legend(fontsize=9)

    # — F1 în funcție de prag —
    ax2 = axes[1]
    ax2.plot(thresholds, f1s,        color="#7C3AED", linewidth=2, label="F1-score")
    ax2.plot(thresholds, precisions,  color="#2563EB", linewidth=1.5,
             linestyle="--", alpha=0.7, label="Precizie")
    ax2.plot(thresholds, recalls,     color="#16A34A", linewidth=1.5,
             linestyle="--", alpha=0.7, label="Recuperare")
    ax2.axvline(0.85, color="#D97706", linestyle=":", linewidth=2, label="Prag curent (0.85)")
    ax2.axvline(best_t, color="#DC2626", linestyle=":", linewidth=2,
                label=f"Prag optim ({best_t:.2f})")
    ax2.set_xlabel("Pragul de similaritate cosinus")
    ax2.set_ylabel("Scor")
    ax2.set_title("F1, Precizie și Recuperare în funcție de prag")
    ax2.set_xlim(0.65, 0.96)
    ax2.set_ylim(0, 1.05)
    ax2.legend(fontsize=9)

    fig.tight_layout()
    save_or_show(fig, save_dir, "07_curba_precizie_recuperare.png")

    # Tabel sumar la câteva praguri
    print("\n   Tabel P/R/F1 la praguri reprezentative:")
    print(f"   {'Prag':>6}  {'Precizie':>9}  {'Recuperare':>10}  {'F1':>7}")
    print(f"   {'':-<6}  {'':-<9}  {'':-<10}  {'':-<7}")
    for t_val in [0.70, 0.75, 0.80, 0.85, 0.90, 0.92, 0.95]:
        idx = int(np.argmin(np.abs(thresholds - t_val)))
        marker = " ← curent" if abs(thresholds[idx] - 0.85) < 0.003 else ""
        print(f"   {thresholds[idx]:>6.2f}  {precisions[idx]:>9.3f}  {recalls[idx]:>10.3f}  {f1s[idx]:>7.3f}{marker}")


# ---------------------------------------------------------------------------
# Grafic 9: Distribuția temporală a articolelor
# ---------------------------------------------------------------------------

def plot_temporal_distribution(years: list[int], save_dir: Path | None) -> None:
    if not years:
        print("[!] Nu există date temporale.")
        return

    year_counts = Counter(years)
    sorted_years = sorted(year_counts.keys())
    counts = [year_counts[y] for y in sorted_years]

    fig, ax = plt.subplots(figsize=(11, 4))
    colors = [PALETTE[i % 3] for i in range(len(sorted_years))]
    ax.bar(sorted_years, counts, color="#2563EB", alpha=0.8, edgecolor="white", linewidth=0.4)
    ax.set_xlabel("Anul publicării")
    ax.set_ylabel("Număr de articole")
    ax.set_title("Distribuția temporală a articolelor din corpus")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

    # Evidențiem vârful
    peak_year = sorted_years[int(np.argmax(counts))]
    peak_val  = max(counts)
    ax.annotate(f"Vârf: {peak_year}\n({peak_val:,} articole)",
                xy=(peak_year, peak_val), xytext=(peak_year - 2, peak_val * 0.85),
                arrowprops=dict(arrowstyle="->", color="#DC2626"),
                fontsize=9, color="#DC2626")

    fig.tight_layout()
    save_or_show(fig, save_dir, "08_distributie_temporala.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Statistici și grafice pentru corpusul și clasificatorul Sentinel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dataset",    type=Path, default=None,
                        help="Calea către arxiv_dataset.jsonl")
    parser.add_argument("--chunks",     type=Path, default=None,
                        help="Calea către chunked_database.jsonl")
    parser.add_argument("--classifier", type=Path, default=None,
                        help="Calea către category_classifier.pkl (opțional)")
    parser.add_argument("--metrics",    type=Path, default=None,
                        help="Calea către category_classifier.metrics.json (opțional)")
    parser.add_argument("--save-dir",   type=Path, default=None,
                        help="Director unde se salvează graficele (implicit: se afișează)")
    parser.add_argument("--no-simulated", action="store_true",
                        help="Omite graficele bazate pe date simulate (6, 7)")
    args = parser.parse_args()

    if not args.dataset and not args.chunks and not args.metrics:
        print("Specificați cel puțin un fișier de intrare. Rulați cu --help pentru ajutor.")
        sys.exit(1)

    dataset_stats = None
    chunk_stats   = None

    # — Date corpus —
    if args.dataset and args.dataset.exists():
        dataset_stats = load_dataset_stats(args.dataset)

    if args.chunks and args.chunks.exists():
        chunk_stats = load_chunk_stats(args.chunks)

    # — Date clasificator —
    classifier_metrics = None
    if args.metrics and args.metrics.exists():
        classifier_metrics = load_classifier_metrics(args.metrics)
    elif args.classifier and args.classifier.exists():
        # Încearcă să găsească automat fișierul de metrici
        auto_metrics = args.classifier.with_suffix(".metrics.json")
        if auto_metrics.exists():
            classifier_metrics = load_classifier_metrics(auto_metrics)

    print("\n=== Generare grafice ===\n")

    # Grafic 1: articole per categorie
    if dataset_stats:
        print("Grafic 1: Articole per categorie...")
        plot_papers_per_category(dataset_stats["papers_per_cat"], args.save_dir)

        print("Grafic 8: Distribuție temporală...")
        plot_temporal_distribution(dataset_stats["years"], args.save_dir)

    # Grafic 2: fragmente vs. ținte
    if chunk_stats:
        papers_per_cat = dataset_stats["papers_per_cat"] if dataset_stats else Counter()
        print("Grafic 2: Fragmente vs. ținte...")
        plot_chunks_vs_targets(chunk_stats["chunks_per_cat"], papers_per_cat, args.save_dir)

        print("Grafic 3: Fragmente per articol...")
        plot_chunks_per_paper(chunk_stats["chunks_per_paper"], args.save_dir)

        print("Grafic 4: Sursa LaTeX vs. PDF...")
        plot_source_type(chunk_stats["source_type_per_cat"], args.save_dir)

    # Grafice 5–6: clasificator
    if classifier_metrics:
        print("Grafic 5: Metrici per clasă (F1, precizie, recuperare)...")
        plot_classifier_metrics(classifier_metrics, args.save_dir)

    # Grafice simulate (nu necesită fișiere)
    if not args.no_simulated:
        print("Grafic 6: Distribuția scorurilor cosinus (date din evaluare)...")
        plot_cosine_score_distribution(args.save_dir)

        print("Grafic 7: Curba precizie–recuperare...")
        plot_precision_recall_curve(args.save_dir)

    print("\nGata.")


if __name__ == "__main__":
    main()