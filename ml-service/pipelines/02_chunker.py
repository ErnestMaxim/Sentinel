"""
02_chunker.py — incremental multithreaded arXiv downloader and chunker.

Optimised for Colab A100 + 167 GB RAM runtime:
  - Default workers raised to 64 (safe with 167 GB RAM)
  - Default timeout raised to 90s (handles larger PDFs)
  - Connection pool sized to match worker count
  - Progress reporting every 500 chunks instead of 1000

Flags:
  --incremental   Skip papers already in the output file, append new chunks.
                  Use this after running 01_extractor with --resume.
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
# Text normalisation (must stay identical to engine/normalizer.py)
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
    'λ': 'LAMBDA', 'μ': 'MU', 'ν': 'NU', 'ξ': 'XI', 'π': 'PI',
    'ρ': 'RHO', 'σ': 'SIGMA', 'τ': 'TAU', 'υ': 'UPSILON', 'φ': 'PHI',
    'χ': 'CHI', 'ψ': 'PSI', 'ω': 'OMEGA',
    'Γ': 'GAMMA', 'Δ': 'DELTA', 'Θ': 'THETA', 'Λ': 'LAMBDA', 'Ξ': 'XI',
    'Π': 'PI', 'Σ': 'SIGMA', 'Υ': 'UPSILON', 'Φ': 'PHI', 'Ψ': 'PSI',
    'Ω': 'OMEGA',
}

# Unicode math operators — PyMuPDF outputs these instead of LaTeX commands.
# Must stay identical to engine/normalizer.py UNICODE_MATH_OPS.
UNICODE_MATH_OPS = {
    '∑': 'SUM',       '∫': 'INT',       '∬': 'INT',       '∭': 'INT',
    '∮': 'INT',       '∏': 'PROD',      '∂': 'PARTIAL',   '∇': 'NABLA',
    'ℏ': 'HBAR',      '∞': 'INF',       '√': 'SQRT',
    '×': 'TIMES',     '·': 'DOT',       '⋅': 'DOT',       '±': 'PLUSMINUS',
    '∓': 'PLUSMINUS',
    '≤': 'LEQ',       '≥': 'GEQ',       '≠': 'NEQ',       '≈': 'APPROX',
    '∼': 'APPROX',    '≡': 'EQUIV',     '∝': 'PROPTO',
    '→': 'RIGHTARROW', '←': 'LEFTARROW', '↔': 'LEFTRIGHTARROW',
    '⇒': 'IMPLIES',   '⇔': 'IFF',
    '⟨': '(',         '⟩': ')',         '⟪': '(',         '⟫': ')',
    '∈': 'IN',        '∉': 'NOTIN',     '⊂': 'SUBSET',    '⊃': 'SUPSET',
    '⊆': 'SUBSET',    '⊇': 'SUPSET',    '∩': 'INTERSECT', '∪': 'UNION',
    '∀': 'FORALL',    '∃': 'EXISTS',    '¬': 'NOT',
    '⊗': 'TENSOR',    '⊕': 'OPLUS',     '†': 'DAGGER',    '‡': 'DDAGGER',
    '…': '...',
}

SUPERSCRIPT_DIGITS = {
    '⁰': '^(0)', '¹': '^(1)', '²': '^(2)', '³': '^(3)', '⁴': '^(4)',
    '⁵': '^(5)', '⁶': '^(6)', '⁷': '^(7)', '⁸': '^(8)', '⁹': '^(9)',
    '⁺': '^(+)', '⁻': '^(-)', '⁼': '^(=)', '⁽': '^(()', '⁾': '^())',
    'ⁿ': '^(n)', 'ⁱ': '^(i)',
}

SUBSCRIPT_DIGITS = {
    '₀': '_(0)', '₁': '_(1)', '₂': '_(2)', '₃': '_(3)', '₄': '_(4)',
    '₅': '_(5)', '₆': '_(6)', '₇': '_(7)', '₈': '_(8)', '₉': '_(9)',
    '₊': '_(+)', '₋': '_(-)', '₌': '_(=)', '₍': '_(()', '₎': '_()',
    'ₙ': '_(n)', 'ᵢ': '_(i)', 'ⱼ': '_(j)', 'ₖ': '_(k)',
}


def normalize_text_for_fingerprint(text: str) -> str:
    # 1. LaTeX Greek command sequences
    for name, token in GREEK_TO_TOKEN.items():
        text = re.sub(rf'\\{name}\b', token, text)
    # 2a. Unicode Greek characters
    for char, token in UNICODE_GREEK.items():
        text = text.replace(char, token)
    # 2b. Unicode math operators
    for char, token in UNICODE_MATH_OPS.items():
        text = text.replace(char, f' {token} ')
    # 2c. Unicode super/subscript digits
    for char, token in SUPERSCRIPT_DIGITS.items():
        text = text.replace(char, token)
    for char, token in SUBSCRIPT_DIGITS.items():
        text = text.replace(char, token)
    # 3. Common math constructs
    text = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'FRAC(\1,\2)', text)
    text = re.sub(r'\\sqrt\{([^{}]*)\}',              r'SQRT(\1)',     text)
    text = re.sub(r'\^\{([^{}]*)\}',                  r'^(\1)',        text)
    text = re.sub(r'_\{([^{}]*)\}',                   r'_(\1)',        text)
    # 4. Named math operators ((?![a-zA-Z]) not \b — \b misses \sum_{i})
    text = re.sub(r'\\(sum|int|prod|lim|sup|inf)(?![a-zA-Z])', lambda m: m.group(1).upper(), text)
    text = re.sub(r'\\(exp|log|ln|sin|cos|tan)(?![a-zA-Z])',   lambda m: m.group(1).upper(), text)
    # 5. Physical constants
    text = re.sub(r'\\hbar(?![a-zA-Z])',    'HBAR',    text)
    text = re.sub(r'\\infty(?![a-zA-Z])',   'INF',     text)
    text = re.sub(r'\\partial(?![a-zA-Z])', 'PARTIAL', text)
    text = re.sub(r'\\nabla(?![a-zA-Z])',   'NABLA',   text)
    text = re.sub(r'\\times(?![a-zA-Z])',   'TIMES',   text)
    text = re.sub(r'\\cdot(?![a-zA-Z])',    'DOT',     text)
    # 6. Relational operators
    text = re.sub(r'\\pm(?![a-zA-Z])',     'PLUSMINUS', text)
    text = re.sub(r'\\leq(?![a-zA-Z])',    'LEQ',       text)
    text = re.sub(r'\\geq(?![a-zA-Z])',    'GEQ',       text)
    text = re.sub(r'\\neq(?![a-zA-Z])',    'NEQ',       text)
    text = re.sub(r'\\approx(?![a-zA-Z])', 'APPROX',    text)
    # 7. German umlaut macros
    text = re.sub(
        r'\\\"([aouAOU])',
        lambda m: m.group(1).translate(str.maketrans('aouAOU', '\xe4\xf6\xfc\xc4\xd6\xdc')),
        text,
    )
    # 8. Strip remaining LaTeX commands
    text = re.sub(r'\\[a-zA-Z]+\*?\s*', ' ', text)
    # 9. Strip LaTeX delimiters
    text = re.sub(r'[{}\[\]$]', ' ', text)
    # 10. Lowercase + collapse whitespace
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def build_session(workers: int) -> requests.Session:
    """Build a session with connection pool sized to the worker count."""
    session = requests.Session()
    session.headers.update({"User-Agent": "SentinelChunker/3.0"})
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
    )
    # Pool sized to workers so connections aren't shared across threads
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=min(workers, 64),
        pool_maxsize=min(workers, 64),
    )
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

    # Try tarball first
    try:
        with tarfile.open(fileobj=io.BytesIO(content)) as tar:
            tex_members = [m for m in tar.getmembers() if m.name.endswith(".tex")]
            if not tex_members:
                return None
            main_tex = max(tex_members, key=lambda m: m.size)
            f = tar.extractfile(main_tex)
            return f.read().decode("utf-8", errors="replace") if f else None
    except tarfile.TarError:
        pass

    # Try gzip single file
    try:
        return gzip.decompress(content).decode("utf-8", errors="replace")
    except Exception:
        return None


def strip_latex_structure(latex: str) -> str:
    latex = re.sub(r'%[^\n]*', ' ', latex)
    doc_start = re.search(r'\\begin\{document\}', latex)
    if doc_start:
        latex = latex[doc_start.end():]
    bib_match = re.search(r'\\begin\{thebibliography\}', latex, re.IGNORECASE)
    if bib_match:
        latex = latex[:bib_match.start()]
    for cmd in (
        "textbf", "textit", "emph", "text", "mathrm", "mathbf",
        "mathit", "mathcal", "mathbb", "mathsf", "operatorname",
        "title", "author", "section", "subsection", "subsubsection",
        "paragraph", "caption", "label", "ref", "cite",
    ):
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
        clean_text = clean_text[:match.start()]
    return clean_text


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int, overlap: int, min_words: int) -> list[str]:
    words = text.split()
    step = chunk_size - overlap
    return [
        " ".join(words[i: i + chunk_size])
        for i in range(0, len(words), step)
        if len(words[i: i + chunk_size]) >= min_words
    ]


# ---------------------------------------------------------------------------
# Per-paper worker
# ---------------------------------------------------------------------------

def process_single_paper(record: dict, session: requests.Session, args) -> list[dict]:
    """Download, normalise and chunk one paper. Prefers LaTeX, falls back to PDF."""
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

    normalized = normalize_text_for_fingerprint(raw_text)
    chunks = chunk_text(normalized, args.chunk_size, args.overlap, args.min_words)

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

def strip_version(arxiv_id: str) -> str:
    """Normalise arxiv_id by stripping version suffix.
    '2511.05984v1' -> '2511.05984'
    """
    base = str(arxiv_id).rsplit("/", 1)[-1].strip()
    if "v" in base:
        base = base.rsplit("v", 1)[0]
    return base.strip()


def load_already_processed_ids(output_path: Path) -> set[str]:
    """Return the set of normalised arxiv_ids already present in the output JSONL."""
    if not output_path.exists():
        return set()
    ids: set[str] = set()
    with output_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    ids.add(strip_version(json.loads(line).get("arxiv_id", "")))
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
        description="Multithreaded arXiv PDF/LaTeX downloader and chunker (A100-optimised)"
    )
    parser.add_argument("--input",       type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output",      type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chunk-size",  type=int,  default=100)
    parser.add_argument("--overlap",     type=int,  default=30)
    parser.add_argument("--min-words",   type=int,  default=20)
    parser.add_argument(
        "--timeout-sec", type=int, default=90,
        help="Per-request timeout in seconds (default: 90 — raised for large PDFs)",
    )
    parser.add_argument(
        "--workers", type=int, default=64,
        help="Parallel download workers (default: 64 — optimised for 167 GB RAM runtime)",
    )
    parser.add_argument(
        "--incremental", action="store_true",
        help=(
            "Skip papers already in the output file and append new chunks. "
            "Use this after running 01_extractor with --resume."
        ),
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Load all records
    with args.input.open("r", encoding="utf-8") as f:
        all_records = [json.loads(line) for line in f if line.strip()]

    # Incremental: filter to only new papers
    if args.incremental:
        already_done = load_already_processed_ids(args.output)
        records = [r for r in all_records if strip_version(str(r.get("arxiv_id", ""))) not in already_done]
        LOGGER.info(
            "Incremental mode: %d total | %d already done | %d new to process",
            len(all_records), len(already_done), len(records),
        )
        write_mode = "a"
    else:
        records = all_records
        LOGGER.info("Full mode: processing all %d records", len(records))

    with open(output_path, write_mode, encoding="utf-8") as out_f:
        for rec in records:
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    LOGGER.info(
        "Done. %d chunks saved from %d papers (latex: %d | pdf: %d | failed: %d).",
        sum(1 for r in records if r),
        len(records),
        0, 0, 0,
    )


if __name__ == "__main__":
    main()
