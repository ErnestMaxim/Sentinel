from __future__ import annotations

# ---------------------------------------------------------------------------
# arXiv API
# ---------------------------------------------------------------------------
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_PDF_URL = "https://export.arxiv.org/pdf/{arxiv_id}.pdf"
ARXIV_SRC_URL = "https://export.arxiv.org/src/{arxiv_id}"

ATOM_NS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "arxiv":  "http://arxiv.org/schemas/atom",
}

# ---------------------------------------------------------------------------
# Model / FAISS defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_NPROBE = 20

# ---------------------------------------------------------------------------
# Category code <-> name mapping
# Classifier outputs human-readable names; FAISS index files use arXiv codes.
# ---------------------------------------------------------------------------
CATEGORY_CODE_TO_NAME: dict[str, str] = {
    "astro-ph":  "Astrophysics",
    "cond-mat":  "Condensed Matter",
    "cs":        "Computer Science",
    "econ":      "Economics",
    "eess":      "Electrical Engineering and Systems Science",
    "gr-qc":     "General Relativity and Quantum Cosmology",
    "hep-ex":    "High Energy Physics - Experiment",
    "hep-lat":   "High Energy Physics - Lattice",
    "hep-ph":    "High Energy Physics - Phenomenology",
    "hep-th":    "High Energy Physics - Theory",
    "math":      "Mathematics",
    "math-ph":   "Mathematical Physics",
    "nlin":      "Nonlinear Sciences",
    "nucl-ex":   "Nuclear Experiment",
    "nucl-th":   "Nuclear Theory",
    "physics":   "Physics",
    "q-bio":     "Quantitative Biology",
    "q-fin":     "Quantitative Finance",
    "quant-ph":  "Quantum Physics",
    "stat":      "Statistics",
}

CATEGORY_NAME_TO_CODE: dict[str, str] = {
    v: k for k, v in CATEGORY_CODE_TO_NAME.items()
}