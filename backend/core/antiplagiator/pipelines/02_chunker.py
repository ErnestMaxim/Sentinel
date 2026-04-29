"""
02_chunker.py — incremental version.

New flag: --incremental
  When set, reads the existing chunked_database.jsonl to find already-processed
  arxiv_ids, then only downloads and chunks papers that are not yet in the DB.
  Appends new chunks to the existing file instead of overwriting it.

Usage (first run — normal):
  python 02_chunker.py

Usage (after extractor adds new papers):
  python 02_chunker.py --incremental
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import re
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ARXIV_PDF_URL = "https://export.arxiv.org/pdf/{arxiv_id}.pdf"
ARXIV_SRC_URL = "https://export.arxiv.org/src/{arxiv_id}"

DEFAULT_INPUT  = Path("backend/core/antiplagiator/data/raw/arxiv_dataset.jsonl")
DEFAULT_OUTPUT = Path("backend/core/antiplagiator/data/processed/chunked_database.jsonl")

file_write_lock = threading.Lock()
LOGGER = logging.getLogger("chunker")


# ---------------------------------------------------------------------------
# Normalisation (identical to engine.py — do not change independently)
# ---------------------------------------------------------------------------

GREEK_TO_TOKEN = {
    "alpha": "ALPHA", "beta": "BETA", "gamma": "GAMMA", "delta": "DELTA",
    "epsilon": "EPSILON", "zeta": "ZETA", "eta": "ETA", "theta": "THETA",
    "iota": "IOTA", "kappa": "KAPPA", "lambda": "LAMBDA", "mu": "MU",
    "nu": "NU", "xi": "XI", "pi": "PI", "rho": "RHO", "sigma": "SIGMA",
    "tau": "TAU", "upsilon": "UPSILON", "phi": "PHI", "chi": "CHI",
    "psi": "PSI", "omega": "OMEGA",
    "Gamma": "GAMMA", "Delta": "DELTA", "Theta": "THETA", "Lambda": "LAMBDA",
    "Xi": "XI", "Pi": "PI", "Sigma": "SIGMA", "Upsilon": "UPSILON",
    "Phi": "PHI", "Psi": "PSI", "Omega": "OMEGA",
}

UNICODE_GREEK = {
    'α': 'ALPHA', 'β': 'BETA', 'γ': 'GAMMA', 'δ': 'DELTA', 'ε': 'EPSILON',
    'ζ': 'ZETA', 'η': 'ETA', 'θ': 'THETA', 'ι': 'IOTA', 'κ': 'KAPPA',
    'λ': 'LAMBDA', 'μ': 'MU', 'ν': 'NU', 'ξ': 'XI', 'π': 'PI', 'ρ': 'RHO',
    'σ': 'SIGMA', 'τ': 'TAU', 'υ': 'UPSILON', 'φ': 'PHI', 'χ': 'CHI',
    'ψ': 'PSI', 'ω': 'OMEGA', 'Γ': 'GAMMA', 'Δ': 'DELTA', 'Θ': 'THETA',
    'Λ': 'LAMBDA', 'Ξ': 'XI', 'Π': 'PI', 'Σ': 'SIGMA', 'Υ': 'UPSILON',
    'Φ': 'PHI', 'Ψ': 'PSI', 'Ω': 'OMEGA',
}


def normalize_text_for_fingerprint(text: str) -> str:
    for name, token in GREEK_TO_TOKEN.items():
        text = re.sub(rf'\\{name}\b', token, text)
    for char, token in UNICODE_GREEK.items():
        text = text.replace(char, token)
    text = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'FRAC(\1,\2)', text)
    text = re.sub(r'\\sqrt\{([^{}]*)\}', r'SQRT(\1)', text)
    text = re.sub(r'\^\{([^{}]*)\}', r'^(\1)', text)
    text = re.sub(r'_\{([^{}]*)\}', r'_(\1)', text)
    text = re.sub(r'\\(sum|int|prod|lim|sup|inf)\b', lambda m: m.group(1).upper(), text)
    text = re.sub(r'\\(exp|log|ln|sin|cos|tan)\b', lambda m: m.group(1).upper(), text)
    text = re.sub(r'\\hbar\b', 'HBAR', text)
    text = re.sub(r'\\infty\b', 'INF', text)
    text = re.sub(r'\\partial\b', 'PARTIAL', text)
    text = re.sub(r'\\nabla\b', 'NABLA', text)
    text = re.sub(r'\\times\b', 'TIMES', text)
    text = re.sub(r'\\cdot\b', 'DOT', text)
    text = re.sub(r'\\pm\b', 'PLUSMINUS', text)
    text = re.sub(r'\\leq\b', 'LEQ', text)
    text = re.sub(r'\\geq\b', 'GEQ', text)
    text = re.sub(r'\\neq\b', 'NEQ', text)
    text = re.sub(r'\\approx\b', 'APPROX', text)
    text = re.sub(r'\\\"([aouAOU])', lambda m: m.group(1).translate(
        str.maketrans('aouAOU', 'äöüÄÖÜ')), text)
    text = re.sub(r'\\[a-zA-Z]+\*?\s*', ' ', text)
    text = re.sub(r'[{}\[\]$]', ' ', text)
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "SentinelChunker/2.0"})
    retry = Retry(
        total=3, backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    return session


# ---------------------------------------------------------------------------
# LaTeX / PDF extraction
# ---------------------------------------------------------------------------

def fetch_latex_source(arxiv_id: str, session: requests.Session, timeout: int) -> str | None:
    url = ARXIV_SRC_URL.format(arxiv_id=arxiv_id)
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        content = resp.content
    except Exception:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(content)) as tar:
            tex_members = [m for m in tar.getmembers() if m.name.endswith(".tex")]
            if not tex_members:
                return None
            main_tex = max(tex_members, key=lambda m: m.size)
            f = tar.extractfile(main_tex)
            if f is None:
                return None
            return f.read().decode("utf-8", errors="replace")
    except tarfile.TarError:
        pass
    try:
        return gzip.decompress(content).decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def strip_latex_structure(latex: str) -> str:
    latex = re.sub(r'%[^\n]*', ' ', latex)
    doc_start = re.search(r'\\begin\{document\}', latex)
    if doc_start:
        latex = latex[doc_start.end():]
    bib_match = re.search(r'\\begin\{thebibliography\}', latex, re.IGNORECASE)
    if bib_match:
        latex = latex[:bib_match.start()]
    for cmd in ("textbf", "textit", "emph", "text", "mathrm", "mathbf",
                "mathit", "mathcal", "mathbb", "mathsf", "operatorname",
                "title", "author", "section", "subsection", "subsubsection",
                "paragraph", "caption", "label", "ref", "cite"):
        latex = re.sub(rf'\\{cmd}\*?\{{([^{{}}]*)\}}', r'\1', latex)
    latex = re.sub(r'\\(begin|end)\{[^}]*\}', ' ', latex)
    return latex


def extract_and_clean_pdf_text(pdf_bytes: bytes) -> str:
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        raw_text = " ".join(page.get_text("text") for page in doc)
    clean_text = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', raw_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    match = re.search(r"\b(References|Bibliography)\b", clean_text, flags=re.IGNORECASE)
    if match and match.start() > (len(clean_text) * 0.75):
        clean_text = clean_text[: match.start()]
    return clean_text


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int, overlap: int, min_words: int) -> list[str]:
    words = text.split()
    step = chunk_size - overlap
    chunks: list[str] = []
    for i in range(0, len(words), step):
        chunk_words = words[i: i + chunk_size]
        if len(chunk_words) >= min_words:
            chunks.append(" ".join(chunk_words))
    return chunks


# ---------------------------------------------------------------------------
# Per-paper worker
# ---------------------------------------------------------------------------

def process_single_paper(record: dict, session: requests.Session, args) -> list[dict]:
    """Download, normalize and chunk a single paper. Prefers LaTeX source over PDF."""
    arxiv_id     = str(record.get("arxiv_id",     "")).strip()
    title        = str(record.get("title",        "")).strip()
    top_category = str(record.get("top_category", "unknown")).strip()

    if not arxiv_id:
        return []

    raw_text: str | None = None
    source_type = "unknown"

    # Attempt 1: LaTeX source
    latex = fetch_latex_source(arxiv_id, session, args.timeout_sec)
    if latex:
        raw_text = strip_latex_structure(latex)
        source_type = "latex"

    # Attempt 2: PDF fallback
    if not raw_text or len(raw_text.split()) < args.min_words:
        try:
            url = ARXIV_PDF_URL.format(arxiv_id=arxiv_id)
            resp = session.get(url, timeout=args.timeout_sec)
            resp.raise_for_status()
            raw_text = extract_and_clean_pdf_text(resp.content)
            source_type = "pdf"
        except Exception:
            return []

    if not raw_text:
        return []

    normalized_text = normalize_text_for_fingerprint(raw_text)
    chunks = chunk_text(normalized_text, args.chunk_size, args.overlap, args.min_words)

    return [
        {
            "arxiv_id":     arxiv_id,
            "title":        title,
            "chunk_id":     i,
            "text":         chunk,
            "source_type":  source_type,
            "top_category": top_category,
        }
        for i, chunk in enumerate(chunks)
    ]


# ---------------------------------------------------------------------------
# Incremental helper
# ---------------------------------------------------------------------------

def load_already_processed_ids(output_path: Path) -> set[str]:
    """Read existing chunked_database.jsonl and return the set of arxiv_ids already in it."""
    if not output_path.exists():
        return set()
    ids: set[str] = set()
    with output_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    ids.add(str(json.loads(line).get("arxiv_id", "")))
                except json.JSONDecodeError:
                    continue
    LOGGER.info("Found %d already-chunked arxiv_ids in %s", len(ids), output_path)
    return ids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    parser = argparse.ArgumentParser(
        description="Multithreaded ArXiv PDF/LaTeX Downloader and Chunker (incremental)"
    )
    parser.add_argument("--input",       type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output",      type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chunk-size",  type=int,  default=100)
    parser.add_argument("--overlap",     type=int,  default=30)
    parser.add_argument("--min-words",   type=int,  default=20)
    parser.add_argument("--timeout-sec", type=int,  default=45)
    parser.add_argument("--workers",     type=int,  default=8)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Skip papers already present in the output file. "
            "Appends new chunks instead of overwriting. "
            "Use this after running the extractor with --resume."
        ),
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Load all records from the dataset JSONL
    with args.input.open("r", encoding="utf-8") as f:
        all_records = [json.loads(line) for line in f if line.strip()]

    # In incremental mode, filter to only new papers
    if args.incremental:
        already_done = load_already_processed_ids(args.output)
        records = [r for r in all_records if str(r.get("arxiv_id", "")) not in already_done]
        LOGGER.info(
            "Incremental mode: %d total records, %d already done, %d new to process",
            len(all_records), len(already_done), len(records),
        )
        write_mode = "a"  # append to existing file
    else:
        records = all_records
        LOGGER.info("Full mode: processing all %d records", len(records))
        write_mode = "w"  # overwrite

    if not records:
        LOGGER.info("Nothing new to process. Exiting.")
        return

    session = build_session()
    total_saved  = 0
    latex_count  = 0
    pdf_count    = 0

    LOGGER.info(
        "Starting %d documents using %d parallel workers (LaTeX preferred, PDF fallback)...",
        len(records), args.workers,
    )

    with args.output.open(write_mode, encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_single_paper, rec, session, args): rec
                for rec in records
            }

            for future in as_completed(futures):
                result_rows = future.result()
                if result_rows:
                    with file_write_lock:
                        for row in result_rows:
                            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        total_saved += len(result_rows)
                        src = result_rows[0].get("source_type", "unknown")
                        if src == "latex":
                            latex_count += 1
                        elif src == "pdf":
                            pdf_count += 1

                if total_saved % 1000 == 0 and total_saved > 0:
                    LOGGER.info(
                        "-> Saved %d chunks so far (latex: %d, pdf: %d)",
                        total_saved, latex_count, pdf_count,
                    )

    LOGGER.info(
        "Finished! Saved %d new chunks. LaTeX: %d papers | PDF: %d papers.",
        total_saved, latex_count, pdf_count,
    )


if __name__ == "__main__":
    main()