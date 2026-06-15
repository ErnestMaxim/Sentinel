"""
evaluate_sentinel.py — Script de evaluare experimentală Sentinel
================================================================
Rulare din folderul ml-service/:

    python evaluate_sentinel.py \\
        --artifacts-dir artifacts/ \\
        --data-dir antiplagiator/data/processed/ \\
        --corpus-jsonl antiplagiator/data/processed/chunked_database.jsonl \\
        --openai-key sk-...

Produce la final tabelele LaTeX gata de inserat în lucrare.

Dependențe suplimentare față de ml-service:
    pip install openai
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import random
import sys
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
LOGGER = logging.getLogger("evaluate")

# ── Parametri scenarii ────────────────────────────────────────────────────────

N_SCENARIO1     = 50    # nr. articole pentru copiere directă
CHUNKS_PER_DOC  = 3     # fragmente extrase per articol
BASE_TEXT_WORDS = 1000  # cuvinte text neutru
N_SCENARIO2     = 30    # nr. fragmente pentru parafraze
N_SCENARIO3     = 20    # nr. articole recente pentru fals-pozitive

THRESHOLD_EXACT = 0.85
THRESHOLD_PARA  = 0.08  # pragul de recuperare în modul parafraze

SEED = 42


# ─────────────────────────────────────────────────────────────────────────────
# Încărcare engine
# ─────────────────────────────────────────────────────────────────────────────


def load_engine(artifacts_dir: Path, data_dir: Path, modal_url: str, modal_secret: str = ""):
    """
    Încarcă AntiplagiarismEngine folosind Modal ca backend FAISS.
    Setează FAISS_REMOTE_URL înainte de inițializare — engine-ul
    detectează automat variabila și folosește RemoteIndex.
    """
    import os

    engine_py = Path(__file__).parent / "antiplagiator" / "engine.py"
    if not engine_py.exists():
        raise FileNotFoundError(f"Nu am găsit engine.py la {engine_py}")

    # Injectează URL-ul Modal și secretul în mediu ÎNAINTE de import
    os.environ["FAISS_REMOTE_URL"] = modal_url
    if modal_secret:
        os.environ["FAISS_API_SECRET"] = modal_secret
        LOGGER.info("FAISS_REMOTE_URL setat: %s | API_SECRET: setat", modal_url)
    else:
        os.environ.pop("FAISS_API_SECRET", None)
        LOGGER.info("FAISS_REMOTE_URL setat: %s | API_SECRET: gol", modal_url)

    spec = importlib.util.spec_from_file_location("antiplagiator_engine", engine_py)
    module = importlib.util.module_from_spec(spec)
    sys.modules["antiplagiator_engine"] = module
    spec.loader.exec_module(module)

    cls = module.AntiplagiarismEngine

    LOGGER.info("Inițializare engine (mod exact — Modal)...")
    engine_exact = cls(
        artifacts_dir=artifacts_dir,
        data_dir=data_dir,
        use_category_routing=False,
        use_per_category_indexes=False,
        use_reranker=False,
        max_sources=10,
        max_matches_per_source=10,
    )

    LOGGER.info("Inițializare engine (mod parafraze — Modal)...")
    engine_para = cls(
        artifacts_dir=artifacts_dir,
        data_dir=data_dir,
        use_category_routing=False,
        use_per_category_indexes=False,
        use_reranker=True,
        max_sources=10,
        max_matches_per_source=10,
    )

    if not engine_exact.is_ready:
        raise RuntimeError(f"Engine exact nu s-a inițializat: {engine_exact.init_error}")
    if not engine_para.is_ready:
        LOGGER.warning(
            "Engine parafraze nu s-a inițializat (reranker lipsă?): %s",
            engine_para.init_error,
        )

    return engine_exact, engine_para


# ─────────────────────────────────────────────────────────────────────────────
# Helpers corpus
# ─────────────────────────────────────────────────────────────────────────────

def load_corpus_sample(jsonl_path: Path, n_papers: int, rng: random.Random) -> list[dict]:
    """
    Încarcă n_papers articole unice (grupate pe arxiv_id) din corpus.
    Returnează lista de înregistrări cu câmpurile: arxiv_id, title, chunks (list[str])
    """
    LOGGER.info("Citire corpus din %s ...", jsonl_path)
    papers: dict[str, dict] = {}

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            aid = row.get("arxiv_id", "")
            if not aid:
                continue
            if aid not in papers:
                papers[aid] = {
                    "arxiv_id": aid,
                    "title":    row.get("title", ""),
                    "chunks":   [],
                }
            papers[aid]["chunks"].append(row.get("text", ""))

    # Filtrează articolele cu cel puțin CHUNKS_PER_DOC fragmente
    eligible = [p for p in papers.values() if len(p["chunks"]) >= CHUNKS_PER_DOC]
    LOGGER.info("%d articole eligibile din corpus.", len(eligible))

    selected = rng.sample(eligible, min(n_papers, len(eligible)))
    LOGGER.info("Selectate %d articole.", len(selected))
    return selected


def build_neutral_base(word_count: int = BASE_TEXT_WORDS) -> str:
    """Generează un text neutru generic de ~word_count cuvinte."""
    sentence = (
        "This study investigates fundamental aspects of the topic under consideration "
        "using established methodological frameworks from the relevant literature. "
        "The results obtained contribute to a broader understanding of the domain "
        "and are consistent with prior findings reported by independent research groups. "
    )
    words = sentence.split()
    repeat = (word_count // len(words)) + 1
    return " ".join((words * repeat)[:word_count])


def write_temp_txt(content: str) -> Path:
    """Scrie conținut într-un fișier temporar .txt și returnează calea."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.flush()
    return Path(tmp.name)


# ─────────────────────────────────────────────────────────────────────────────
# Scenariul 1 — copiere directă
# ─────────────────────────────────────────────────────────────────────────────

def run_scenario1(engine_exact, corpus_papers: list[dict]) -> dict:
    LOGGER.info("=" * 60)
    LOGGER.info("SCENARIUL 1: Copiere directă (%d documente)", len(corpus_papers))
    LOGGER.info("=" * 60)

    rng = random.Random(SEED)

    top1_correct   = 0
    top3_correct   = 0
    scores         = []
    durations      = []
    verbatim_hits  = 0
    verbatim_total = 0

    for i, paper in enumerate(corpus_papers):
        # Selectează CHUNKS_PER_DOC fragmente din locuri diferite ale articolului
        n = len(paper["chunks"])
        step = max(1, n // CHUNKS_PER_DOC)
        selected_chunks = [paper["chunks"][j * step] for j in range(CHUNKS_PER_DOC)]

        # Construiește documentul: text neutru + fragmente inserate
        base = build_neutral_base(BASE_TEXT_WORDS // (CHUNKS_PER_DOC + 1))
        parts = []
        for chunk in selected_chunks:
            parts.append(base)
            parts.append(chunk)
        parts.append(base)
        document_text = "\n\n".join(parts)

        doc_path = write_temp_txt(document_text)

        t0 = time.monotonic()
        result = engine_exact.analyze_document(
            doc_path,
            threshold=THRESHOLD_EXACT,
            top_k=5,
            arxiv_id=None,
            paraphrase_mode=False,
        )
        duration = time.monotonic() - t0

        doc_path.unlink(missing_ok=True)

        if "error" in result and result.get("total_reported_sources", 1) == 0:
            LOGGER.warning("[S1] Document %d: eroare engine — %s", i + 1, result.get("error"))
            continue

        sources = result.get("sources", [])
        found_ids = [s.get("arxiv_id", "") for s in sources]
        target_id = paper["arxiv_id"]

        # Verifică dacă sursa corectă e în top-1 sau top-3
        in_top1 = len(found_ids) > 0 and found_ids[0] == target_id
        in_top3 = target_id in found_ids[:3]

        if in_top1:
            top1_correct += 1
        if in_top3:
            top3_correct += 1

        score = result.get("global_plagiarism_score_percent", 0.0)
        scores.append(score)
        durations.append(duration)

        # Numără secvențe verbatim așteptate vs. detectate
        for src in sources:
            if src.get("arxiv_id") == target_id:
                for match in src.get("matches", []):
                    verbatim_total += 1
                    if match.get("exact_copied_phrases"):
                        verbatim_hits += 1

        LOGGER.info(
            "[S1] %d/%d | top1=%s | top3=%s | scor=%.1f%% | %.1fs",
            i + 1, len(corpus_papers),
            "✓" if in_top1 else "✗",
            "✓" if in_top3 else "✗",
            score, duration,
        )

    n = len(corpus_papers)
    avg_score = sum(scores) / len(scores) if scores else 0.0
    std_score = (sum((s - avg_score) ** 2 for s in scores) / len(scores)) ** 0.5 if scores else 0.0
    avg_dur   = sum(durations) / len(durations) if durations else 0.0
    std_dur   = (sum((d - avg_dur) ** 2 for d in durations) / len(durations)) ** 0.5 if durations else 0.0
    verbatim_rate = verbatim_hits / verbatim_total * 100 if verbatim_total > 0 else 0.0

    return {
        "n":              n,
        "top1_pct":       top1_correct / n * 100,
        "top3_pct":       top3_correct / n * 100,
        "avg_score":      avg_score,
        "std_score":      std_score,
        "avg_duration":   avg_dur,
        "std_duration":   std_dur,
        "verbatim_pct":   verbatim_rate,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scenariul 2 — parafraze (OpenAI)
# ─────────────────────────────────────────────────────────────────────────────

def generate_paraphrase_openai(text: str, openai_key: str) -> str | None:
    """Generează o parafrază a textului folosind gpt-4o-mini."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("Instalează openai: pip install openai")

    client = OpenAI(api_key=openai_key)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an academic writing assistant. "
                        "Paraphrase the following scientific text completely: "
                        "change all phrasing, sentence structure and word choices, "
                        "but preserve the exact meaning and all technical terms. "
                        "Return only the paraphrased text, no preamble."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=500,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        LOGGER.warning("Eroare OpenAI: %s", e)
        return None


def run_scenario2(
    engine_exact,
    engine_para,
    corpus_papers: list[dict],
    openai_key: str,
) -> dict:
    LOGGER.info("=" * 60)
    LOGGER.info("SCENARIUL 2: Parafraze (%d fragmente)", N_SCENARIO2)
    LOGGER.info("=" * 60)

    rng = random.Random(SEED + 1)

    # Selectează N_SCENARIO2 fragmente aleatorii din corpus
    fragments = []
    for paper in rng.sample(corpus_papers, min(N_SCENARIO2, len(corpus_papers))):
        chunk = rng.choice(paper["chunks"])
        if len(chunk.split()) >= 50:  # minim 50 cuvinte pentru parafraze utile
            fragments.append({"arxiv_id": paper["arxiv_id"], "text": chunk})

    # Completează dacă n-avem destule
    while len(fragments) < N_SCENARIO2 and corpus_papers:
        paper = rng.choice(corpus_papers)
        chunk = rng.choice(paper["chunks"])
        if len(chunk.split()) >= 50:
            fragments.append({"arxiv_id": paper["arxiv_id"], "text": chunk})

    fragments = fragments[:N_SCENARIO2]
    LOGGER.info("Fragmente selectate: %d", len(fragments))

    detected_exact = 0
    detected_para  = 0
    skipped        = 0

    for i, frag in enumerate(fragments):
        LOGGER.info("[S2] Fragment %d/%d — generare parafrază...", i + 1, len(fragments))

        paraphrase = generate_paraphrase_openai(frag["text"], openai_key)
        if not paraphrase:
            LOGGER.warning("[S2] Parafraza %d nu a putut fi generată — skip.", i + 1)
            skipped += 1
            continue

        # Inserează parafraza într-un text neutru
        base = build_neutral_base(500)
        document_text = f"{base}\n\n{paraphrase}\n\n{base}"
        doc_path = write_temp_txt(document_text)

        # Test mod exact
        result_exact = engine_exact.analyze_document(
            doc_path,
            threshold=THRESHOLD_EXACT,
            top_k=5,
            paraphrase_mode=False,
        )
        sources_exact = result_exact.get("sources", [])
        found_exact = any(
            s.get("arxiv_id") == frag["arxiv_id"] for s in sources_exact
        )
        if found_exact:
            detected_exact += 1

        # Test mod parafraze
        if engine_para.is_ready:
            result_para = engine_para.analyze_document(
                doc_path,
                threshold=THRESHOLD_EXACT,
                top_k=5,
                paraphrase_mode=True,
            )
            sources_para = result_para.get("sources", [])
            found_para = any(
                s.get("arxiv_id") == frag["arxiv_id"] for s in sources_para
            )
            if found_para:
                detected_para += 1
        else:
            detected_para = None

        doc_path.unlink(missing_ok=True)

        LOGGER.info(
            "[S2] %d/%d | exact=%s | para=%s",
            i + 1, len(fragments),
            "✓" if found_exact else "✗",
            ("✓" if found_para else "✗") if engine_para.is_ready else "N/A",
        )

    valid = len(fragments) - skipped

    return {
        "n":               valid,
        "skipped":         skipped,
        "detected_exact":  detected_exact,
        "detected_para":   detected_para,
        "rate_exact_pct":  detected_exact / valid * 100 if valid > 0 else 0.0,
        "rate_para_pct":   detected_para / valid * 100 if (detected_para is not None and valid > 0) else None,
        "para_available":  engine_para.is_ready,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scenariul 3 — fals-pozitive (articole absente din corpus)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_recent_arxiv_ids(n: int) -> list[str]:
    """
    Descarcă n articole recente din arXiv (publicate recent, deci absente din corpus).
    Folosește API-ul public arXiv, sortând după data actualizării.
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    LOGGER.info("Descărcare %d articole recente din arXiv...", n)

    url = (
        f"https://export.arxiv.org/api/query"
        f"?search_query=cat:cs.AI"
        f"&sortBy=lastUpdatedDate&sortOrder=descending"
        f"&max_results={n}"
    )

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            xml_data = resp.read()
    except Exception as e:
        LOGGER.error("Eroare la descărcarea din arXiv: %s", e)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)
    ids = []
    for entry in root.findall("atom:entry", ns):
        id_text = entry.findtext("atom:id", default="", namespaces=ns)
        arxiv_id = id_text.rsplit("/", 1)[-1].rsplit("v", 1)[0]
        if arxiv_id:
            ids.append(arxiv_id)

    LOGGER.info("Articole recente obținute: %d", len(ids))
    return ids[:n]


def download_arxiv_abstract(arxiv_id: str) -> str | None:
    """Descarcă rezumatul unui articol arXiv ca text simplu."""
    import urllib.request
    import xml.etree.ElementTree as ET

    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            xml_data = resp.read()
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_data)
        entry = root.find("atom:entry", ns)
        if entry is not None:
            title    = entry.findtext("atom:title", default="", namespaces=ns).strip()
            abstract = entry.findtext("atom:summary", default="", namespaces=ns).strip()
            return f"{title}.\n\n{abstract}"
    except Exception as e:
        LOGGER.warning("Eroare descărcare rezumat %s: %s", arxiv_id, e)
    return None


def run_scenario3(engine_exact, engine_para, corpus_jsonl: Path) -> dict:
    LOGGER.info("=" * 60)
    LOGGER.info("SCENARIUL 3: Fals-pozitive (%d articole recente)", N_SCENARIO3)
    LOGGER.info("=" * 60)

    # Încarcă ID-urile din corpus pentru a verifica absența
    LOGGER.info("Construire set ID-uri corpus...")
    corpus_ids: set[str] = set()
    with corpus_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                aid = json.loads(line).get("arxiv_id", "")
                if aid:
                    corpus_ids.add(aid)
    LOGGER.info("Corpus conține %d ID-uri unice.", len(corpus_ids))

    # Descarcă articole recente
    recent_ids = fetch_recent_arxiv_ids(N_SCENARIO3 * 3)  # supraestimare pentru filtrare
    absent_ids = [aid for aid in recent_ids if aid not in corpus_ids][:N_SCENARIO3]

    if len(absent_ids) < N_SCENARIO3:
        LOGGER.warning(
            "Disponibile doar %d articole absente din corpus (cerute %d).",
            len(absent_ids), N_SCENARIO3
        )

    scores_exact = []
    scores_para  = []

    for i, arxiv_id in enumerate(absent_ids):
        text = download_arxiv_abstract(arxiv_id)
        if not text or len(text.split()) < 50:
            LOGGER.warning("[S3] Rezumat insuficient pentru %s — skip.", arxiv_id)
            continue

        doc_path = write_temp_txt(text)

        # Mod exact
        r_exact = engine_exact.analyze_document(
            doc_path,
            threshold=THRESHOLD_EXACT,
            top_k=5,
            paraphrase_mode=False,
        )
        score_exact = r_exact.get("global_plagiarism_score_percent", 0.0)
        scores_exact.append(score_exact)

        # Mod parafraze
        if engine_para.is_ready:
            r_para = engine_para.analyze_document(
                doc_path,
                threshold=THRESHOLD_EXACT,
                top_k=5,
                paraphrase_mode=True,
            )
            score_para = r_para.get("global_plagiarism_score_percent", 0.0)
            scores_para.append(score_para)

        doc_path.unlink(missing_ok=True)

        LOGGER.info(
            "[S3] %d/%d | %s | exact=%.1f%% | para=%s",
            i + 1, len(absent_ids), arxiv_id, score_exact,
            f"{score_para:.1f}%" if engine_para.is_ready else "N/A",
        )

        # Politicos cu API-ul arXiv
        time.sleep(0.5)

    avg_exact = sum(scores_exact) / len(scores_exact) if scores_exact else 0.0
    std_exact = (sum((s - avg_exact) ** 2 for s in scores_exact) / len(scores_exact)) ** 0.5 if scores_exact else 0.0
    avg_para  = sum(scores_para)  / len(scores_para)  if scores_para  else None
    std_para  = (sum((s - avg_para) ** 2 for s in scores_para) / len(scores_para)) ** 0.5 if scores_para else None

    return {
        "n":           len(scores_exact),
        "avg_exact":   avg_exact,
        "std_exact":   std_exact,
        "avg_para":    avg_para,
        "std_para":    std_para,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Generare tabele LaTeX
# ─────────────────────────────────────────────────────────────────────────────

def fmt(value, decimals=1, suffix=""):
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}{suffix}"


def generate_latex_tables(s1: dict, s2: dict, s3: dict) -> str:
    lines = []

    # ── Tabel 1 ──────────────────────────────────────────────────────────────
    lines.append(r"% ── Tabel Scenariul 1: copiere directă")
    lines.append(r"\begin{table}[ht]")
    lines.append(r"    \centering")
    lines.append(r"    \caption{Rezultatele detecției copierii directe pe "
                 + str(s1['n']) + r" documente construite artificial.}")
    lines.append(r"    \label{tab:eval1}")
    lines.append(r"    \small")
    lines.append(r"    \begin{tabular}{lrr}")
    lines.append(r"        \toprule")
    lines.append(r"        Metrică & Valoare medie & Abatere standard\\")
    lines.append(r"        \midrule")
    lines.append(
        r"        Sursă corectă identificată (primul rezultat) & $"
        + fmt(s1['top1_pct'], 0) + r"\%$ & $-$\\"
    )
    lines.append(
        r"        Sursă corectă în primele trei rezultate       & $"
        + fmt(s1['top3_pct'], 0) + r"\%$ & $-$\\"
    )
    lines.append(
        r"        Scor mediu raportat                           & $"
        + fmt(s1['avg_score']) + r"\%$ & $"
        + fmt(s1['std_score']) + r"\%$\\"
    )
    lines.append(
        r"        Durată medie de procesare (mod exact)         & $"
        + fmt(s1['avg_duration']) + r"$ s & $"
        + fmt(s1['std_duration']) + r"$ s\\"
    )
    lines.append(
        r"        Secvențe verbatim corect identificate         & $"
        + fmt(s1['verbatim_pct'], 0) + r"\%$ & $-$\\"
    )
    lines.append(r"        \bottomrule")
    lines.append(r"    \end{tabular}")
    lines.append(r"\end{table}")
    lines.append("")

    # ── Tabel 2 ──────────────────────────────────────────────────────────────
    lines.append(r"% ── Tabel Scenariul 2: parafraze")
    lines.append(r"\begin{table}[ht]")
    lines.append(r"    \centering")
    lines.append(r"    \caption{Rezultatele detecției parafrazelor pe "
                 + str(s2['n']) + r" fragmente generate automat.}")
    lines.append(r"    \label{tab:eval2}")
    lines.append(r"    \small")
    lines.append(r"    \begin{tabular}{lrr}")
    lines.append(r"        \toprule")
    lines.append(r"        Mod & Fragmente detectate & Rată de recuperare\\")
    lines.append(r"        \midrule")
    lines.append(
        r"        Mod exact (cosinus $\geq " + fmt(THRESHOLD_EXACT) + r"$) & "
        + str(s2['detected_exact']) + "/" + str(s2['n'])
        + r" & $" + fmt(s2['rate_exact_pct'], 0) + r"\%$\\"
    )
    if s2['rate_para_pct'] is not None:
        lines.append(
            r"        Mod parafraze (encoder încrucișat) & "
            + str(s2['detected_para']) + "/" + str(s2['n'])
            + r" & $" + fmt(s2['rate_para_pct'], 0) + r"\%$\\"
        )
    lines.append(r"        \bottomrule")
    lines.append(r"    \end{tabular}")
    lines.append(r"\end{table}")
    lines.append("")

    # ── Tabel 3 ──────────────────────────────────────────────────────────────
    lines.append(r"% ── Tabel Scenariul 3: fals-pozitive")
    lines.append(r"\begin{table}[ht]")
    lines.append(r"    \centering")
    lines.append(r"    \caption{Rata de fals-pozitive pe "
                 + str(s3['n']) + r" documente absente din corpus.}")
    lines.append(r"    \label{tab:eval3}")
    lines.append(r"    \small")
    lines.append(r"    \begin{tabular}{lrr}")
    lines.append(r"        \toprule")
    lines.append(r"        Mod & Scor mediu & Abatere standard\\")
    lines.append(r"        \midrule")
    lines.append(
        r"        Mod exact & $" + fmt(s3['avg_exact']) + r"\%$ & $"
        + fmt(s3['std_exact']) + r"\%$\\"
    )
    if s3['avg_para'] is not None:
        lines.append(
            r"        Mod parafraze & $" + fmt(s3['avg_para']) + r"\%$ & $"
            + fmt(s3['std_para']) + r"\%$\\"
        )
    lines.append(r"        \bottomrule")
    lines.append(r"    \end{tabular}")
    lines.append(r"\end{table}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluare experimentală Sentinel — generează tabele LaTeX"
    )
    parser.add_argument(
        "--artifacts-dir", type=Path, default=Path("artifacts"),
        help="Directorul cu indexul FAISS și clasificatorul",
    )
    parser.add_argument(
        "--data-dir", type=Path,
        default=Path("antiplagiator/data/processed"),
        help="Directorul cu chunked_database.jsonl",
    )
    parser.add_argument(
        "--corpus-jsonl", type=Path,
        default=Path("antiplagiator/data/processed/chunked_database.jsonl"),
        help="Calea exactă spre chunked_database.jsonl",
    )
    parser.add_argument(
        "--openai-key", type=str, default=None,
        help="Cheia API OpenAI pentru generarea parafrazelor (Scenariul 2)",
    )
    parser.add_argument(
        "--output-json", type=Path, default=Path("eval_results.json"),
        help="Fișier JSON cu rezultatele brute",
    )
    parser.add_argument(
        "--output-latex", type=Path, default=Path("eval_tables.tex"),
        help="Fișier .tex cu tabelele gata de inserat",
    )
    parser.add_argument(
        "--skip-scenario", type=int, nargs="*", default=[],
        help="Scenarii de sărit (ex: --skip-scenario 2 3)",
    )
    parser.add_argument(
        "--modal-url", type=str, required=True,
        help="URL-ul endpoint-ului Modal FAISS (ex: https://workspace--sentinel-search.modal.run)",
    )
    parser.add_argument(
        "--modal-secret", type=str, default="",
        help="API_SECRET configurat în Modal Secret (sentinel-secrets). Lăsați gol dacă nu e setat.",
    )
    args = parser.parse_args()

    # Validări
    if not args.corpus_jsonl.exists():
        LOGGER.error("Nu am găsit corpus JSONL: %s", args.corpus_jsonl)
        sys.exit(1)

    # Încărcare engine
    engine_exact, engine_para = load_engine(args.artifacts_dir, args.data_dir, args.modal_url, args.modal_secret)

    # Încărcare eșantion corpus comun pentru S1 și S2
    rng = random.Random(SEED)
    corpus_papers = load_corpus_sample(
        args.corpus_jsonl,
        n_papers=max(N_SCENARIO1, N_SCENARIO2) + 10,
        rng=rng,
    )

    results = {}

    # ── Scenariul 1 ──────────────────────────────────────────────────────────
    if 1 not in args.skip_scenario:
        s1_papers = corpus_papers[:N_SCENARIO1]
        results["scenario1"] = run_scenario1(engine_exact, s1_papers)
    else:
        LOGGER.info("Scenariul 1 sărit.")
        results["scenario1"] = None

    # ── Scenariul 2 ──────────────────────────────────────────────────────────
    if 2 not in args.skip_scenario:
        if not args.openai_key:
            LOGGER.warning("--openai-key lipsă — Scenariul 2 sărit.")
            results["scenario2"] = None
        else:
            s2_papers = corpus_papers[:N_SCENARIO2 + 5]
            results["scenario2"] = run_scenario2(
                engine_exact, engine_para, s2_papers, args.openai_key
            )
    else:
        LOGGER.info("Scenariul 2 sărit.")
        results["scenario2"] = None

    # ── Scenariul 3 ──────────────────────────────────────────────────────────
    if 3 not in args.skip_scenario:
        results["scenario3"] = run_scenario3(engine_exact, engine_para, args.corpus_jsonl)
    else:
        LOGGER.info("Scenariul 3 sărit.")
        results["scenario3"] = None

    # ── Salvare JSON ──────────────────────────────────────────────────────────
    with args.output_json.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    LOGGER.info("Rezultate brute salvate în %s", args.output_json)

    # ── Generare LaTeX ────────────────────────────────────────────────────────
    s1 = results["scenario1"] or {}
    s2 = results["scenario2"] or {}
    s3 = results["scenario3"] or {}

    # Valori implicite dacă un scenariu a fost sărit
    s1 = {**{"n":0,"top1_pct":0,"top3_pct":0,"avg_score":0,"std_score":0,
              "avg_duration":0,"std_duration":0,"verbatim_pct":0}, **s1}
    s2 = {**{"n":0,"detected_exact":0,"detected_para":0,
              "rate_exact_pct":0,"rate_para_pct":None,"para_available":False}, **s2}
    s3 = {**{"n":0,"avg_exact":0,"std_exact":0,"avg_para":None,"std_para":None}, **s3}

    latex = generate_latex_tables(s1, s2, s3)

    with args.output_latex.open("w", encoding="utf-8") as f:
        f.write(latex)
    LOGGER.info("Tabele LaTeX salvate în %s", args.output_latex)

    # ── Sumar terminal ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("REZULTATE FINALE")
    print("=" * 60)

    if results["scenario1"]:
        r = results["scenario1"]
        print(f"\nSCENARIUL 1 — Copiere directă (n={r['n']})")
        print(f"  Top-1 corect    : {r['top1_pct']:.1f}%")
        print(f"  Top-3 corect    : {r['top3_pct']:.1f}%")
        print(f"  Scor mediu      : {r['avg_score']:.1f}% ± {r['std_score']:.1f}%")
        print(f"  Durată medie    : {r['avg_duration']:.1f}s ± {r['std_duration']:.1f}s")
        print(f"  Verbatim        : {r['verbatim_pct']:.1f}%")

    if results["scenario2"]:
        r = results["scenario2"]
        print(f"\nSCENARIUL 2 — Parafraze (n={r['n']})")
        print(f"  Detectate (exact)   : {r['detected_exact']}/{r['n']} ({r['rate_exact_pct']:.1f}%)")
        if r["rate_para_pct"] is not None:
            print(f"  Detectate (parafraze): {r['detected_para']}/{r['n']} ({r['rate_para_pct']:.1f}%)")

    if results["scenario3"]:
        r = results["scenario3"]
        print(f"\nSCENARIUL 3 — Fals-pozitive (n={r['n']})")
        print(f"  Scor mediu (exact)    : {r['avg_exact']:.1f}% ± {r['std_exact']:.1f}%")
        if r["avg_para"] is not None:
            print(f"  Scor mediu (parafraze): {r['avg_para']:.1f}% ± {r['std_para']:.1f}%")

    print(f"\nFișiere generate:")
    print(f"  {args.output_json}")
    print(f"  {args.output_latex}")


if __name__ == "__main__":
    main()