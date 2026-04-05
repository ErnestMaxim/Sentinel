from __future__ import annotations

import argparse
import difflib
import gzip
import io
import json
import logging
import pickle
import re
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import faiss
import fitz
import requests
from requests.adapters import HTTPAdapter
from sentence_transformers import SentenceTransformer
from urllib3.util.retry import Retry


LOGGER = logging.getLogger("plagiarism_engine")

ARXIV_SRC_URL = "https://export.arxiv.org/src/{arxiv_id}"


# ---------------------------------------------------------------------------
# Normalization — must be identical to 02_chunker.py so that the 7-word
# fingerprint windows align correctly between DB and query document.
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
    """
    Canonical normalization applied identically to both the database chunks
    and the query document. Consistent token output is more important than
    human readability — this is what makes the 7-word sliding window match
    correctly across LaTeX source and PDF-extracted text.
    """
    # 1. Greek letters from LaTeX commands → uppercase ASCII tokens
    for name, token in GREEK_TO_TOKEN.items():
        text = re.sub(rf'\\{name}\b', token, text)

    # 2. Unicode Greek (produced by PyMuPDF from PDFs) → same tokens
    for char, token in UNICODE_GREEK.items():
        text = text.replace(char, token)

    # 3. Math structures → canonical tokens
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

    # 4. Accents: \"o → ö, etc.
    text = re.sub(r'\\\"([aouAOU])', lambda m: m.group(1).translate(
        str.maketrans('aouAOU', 'äöüÄÖÜ')), text)

    # 5. Strip remaining LaTeX commands and punctuation noise
    text = re.sub(r'\\[a-zA-Z]+\*?\s*', ' ', text)
    text = re.sub(r'[{}\[\]$]', ' ', text)

    # 6. Lowercase for case-insensitive matching
    text = text.lower()

    # 7. Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# ---------------------------------------------------------------------------
# Device resolution
# ---------------------------------------------------------------------------

def resolve_device(preferred: str) -> str:
    if preferred in {"cpu", "cuda"}:
        return preferred
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "SentinelEngine/3.0"})
    retry = Retry(total=3, backoff_factor=1.0,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods={"GET"})
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AntiplagiarismEngine:
    def __init__(
        self,
        model_name: str = "allenai/specter",
        artifacts_dir: Path = Path("backend/core/antiplagiator/artifacts"),
        data_dir: Path = Path("backend/core/antiplagiator/data/processed"),
        device: str = "auto",
        max_sources: int = 10,
        max_matches_per_source: int = 5,
    ) -> None:
        self.artifacts_dir = artifacts_dir
        self.data_dir = data_dir
        self.device = resolve_device(device)
        self._session = _build_session()
        self.max_sources = max_sources
        self.max_matches_per_source = max_matches_per_source

        LOGGER.info("Initializing AntiplagiarismEngine")
        LOGGER.info("Using device: %s", self.device)
        LOGGER.info("Loading model: %s", model_name)
        self.model = SentenceTransformer(model_name, device=self.device)

        index_path = self.artifacts_dir / "faiss_document_index.bin"
        metadata_path = self.artifacts_dir / "faiss_metadata.pkl"
        dataset_path = self.data_dir / "chunked_database.jsonl"

        if not index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {index_path}")
        if not metadata_path.exists():
            raise FileNotFoundError(f"FAISS metadata not found: {metadata_path}")

        LOGGER.info("Loading FAISS index from %s", index_path)
        self.index = faiss.read_index(str(index_path))

        LOGGER.info("Loading metadata from %s", metadata_path)
        with metadata_path.open("rb") as f:
            self.metadata: list[dict[str, Any]] = pickle.load(f)

        LOGGER.info("Loading dataset texts from %s", dataset_path)
        self.dataset_texts = self._load_dataset_texts(dataset_path)

        LOGGER.info("Engine ready")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_dataset_texts(self, jsonl_path: Path) -> list[str]:
        texts: list[str] = []
        if not jsonl_path.exists():
            LOGGER.warning("Dataset JSONL not found at %s", jsonl_path)
            return texts
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                texts.append(str(data.get("text", "")))
        return texts

    def _fetch_latex_source(self, arxiv_id: str, timeout: int = 30) -> str | None:
        """Fetch raw LaTeX source for an arXiv paper."""
        url = ARXIV_SRC_URL.format(arxiv_id=arxiv_id)
        try:
            resp = self._session.get(url, timeout=timeout)
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

    def _strip_latex_structure(self, latex: str) -> str:
        """Remove LaTeX document structure, keeping text and math content."""
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

    def _read_and_chunk_file(
        self,
        file_path: Path,
        chunk_size: int = 100,
        overlap: int = 30,
        arxiv_id: str | None = None,
    ) -> list[str]:
        """
        Extract text from a local file, normalize it, and split into chunks.
        Normalization is identical to 02_chunker.py so fingerprint windows align.

        Priority:
          1. LaTeX source from arXiv (if arxiv_id provided)
          2. Local .tex file
          3. PDF extraction
          4. Plain text
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be >= 0 and < chunk_size")
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw_text = ""

        # 1. arXiv LaTeX source
        if arxiv_id:
            latex = self._fetch_latex_source(arxiv_id)
            if latex and len(latex.split()) >= 20:
                raw_text = self._strip_latex_structure(latex)
                LOGGER.info("Using arXiv LaTeX source for %s", arxiv_id)

        # 2. Local .tex file
        if not raw_text and file_path.suffix.lower() == ".tex":
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                raw_text = self._strip_latex_structure(f.read())

        # 3. PDF
        if not raw_text and file_path.suffix.lower() == ".pdf":
            with fitz.open(file_path) as doc:
                raw_text = " ".join(page.get_text("text") for page in doc)
            raw_text = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', raw_text)
            raw_text = re.sub(r'\s+', ' ', raw_text).strip()
            match = re.search(r"\b(References|Bibliography)\b", raw_text, flags=re.IGNORECASE)
            if match and match.start() > (len(raw_text) * 0.75):
                raw_text = raw_text[: match.start()]

        # 4. Plain text fallback
        if not raw_text:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()
            raw_text = re.sub(r'\s+', ' ', raw_text).strip()

        # Normalize BEFORE chunking — same contract as 02_chunker.py
        normalized = normalize_text_for_fingerprint(raw_text)

        words = normalized.split()
        step = chunk_size - overlap
        chunks: list[str] = []
        for i in range(0, len(words), step):
            chunk_words = words[i : i + chunk_size]
            if len(chunk_words) >= 20:
                chunks.append(" ".join(chunk_words))

        return chunks

    def _extract_exact_matches(self, query_text: str, db_text: str, min_words: int = 6) -> list[str]:
        """
        Find exact matching phrases between query and DB chunk.
        Both sides are already normalized, so the comparison is consistent.
        """
        matcher = difflib.SequenceMatcher(None, query_text, db_text, autojunk=False)
        exact_phrases: set[str] = set()

        for match in matcher.get_matching_blocks():
            matched_string = query_text[match.a : match.a + match.size].strip()
            if len(matched_string.split()) >= min_words:
                exact_phrases.add(matched_string)

        return list(exact_phrases)

    def _filter_and_rank_sources(
        self,
        sources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Filter and rank sources to keep the report concise and meaningful:
          1. Prefer sources with at least one exact copied phrase
          2. Keep only the top N matches per source (by cosine similarity)
          3. Keep only the top max_sources sources (by match count)
        """
        # Sort matches within each source by cosine similarity descending
        for data in sources.values():
            data["matches"] = sorted(
                data["matches"],
                key=lambda m: m["cosine_similarity"],
                reverse=True,
            )[:self.max_matches_per_source]

        # Prefer sources that have at least one exact copied phrase
        sources_with_exact = {
            arxiv_id: data for arxiv_id, data in sources.items()
            if any(len(m["exact_copied_phrases"]) > 0 for m in data["matches"])
        }

        # Fall back to all sources if none have exact matches
        sources_to_rank = sources_with_exact if sources_with_exact else sources

        # Sort by match count descending, cap at max_sources
        sorted_sources = sorted(
            sources_to_rank.items(),
            key=lambda item: len(item[1]["matches"]),
            reverse=True,
        )[:self.max_sources]

        result = []
        for src_arxiv_id, data in sorted_sources:
            avg_score = sum(m["match_percentage"] for m in data["matches"]) / len(data["matches"])
            result.append(
                {
                    "arxiv_id": src_arxiv_id,
                    "title": data["title"],
                    "match_count": len(data["matches"]),
                    "average_similarity_percent": round(avg_score, 2),
                    "has_exact_copies": any(
                        len(m["exact_copied_phrases"]) > 0 for m in data["matches"]
                    ),
                    "matches": data["matches"],
                }
            )

        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_document(
        self,
        file_path: Path,
        threshold: float = 0.85,
        top_k: int = 5,
        arxiv_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze a document for plagiarism.

        Parameters
        ----------
        file_path : Path
            Local path to the PDF, .tex, or .txt file to analyze.
        threshold : float
            Minimum cosine similarity to flag a match (0–1).
            Default raised to 0.85 to reduce false positives.
        top_k : int
            Number of nearest neighbors to retrieve per chunk.
        arxiv_id : str | None
            Optional arXiv ID of the query document. When provided, the engine
            fetches the original LaTeX source for math-accurate text extraction.
        """
        chunks = self._read_and_chunk_file(file_path, arxiv_id=arxiv_id)
        if not chunks:
            return {"error": "No valid text could be extracted."}

        total_words_in_doc = sum(len(c.split()) for c in chunks)
        if total_words_in_doc == 0:
            return {"error": "Document is empty."}

        query_vectors = self.model.encode(
            chunks, convert_to_numpy=True, normalize_embeddings=True
        )
        similarities, indices = self.index.search(query_vectors, k=top_k)

        sources: dict[str, dict[str, Any]] = defaultdict(lambda: {"title": "", "matches": []})
        plagiarized_words_weighted_sum = 0.0
        unique_flagged_chunks: set[int] = set()

        for query_idx, (score_row, idx_row) in enumerate(zip(similarities, indices)):
            chunk_word_count = len(chunks[query_idx].split())
            chunk_already_flagged = False

            for i in range(top_k):
                raw_cosine_score = float(score_row[i])
                cosine_sim = max(0.0, min(1.0, raw_cosine_score))

                if cosine_sim < threshold:
                    continue

                match_idx = int(idx_row[i])
                if match_idx < 0 or match_idx >= len(self.metadata):
                    continue

                match_data = self.metadata[match_idx]
                arxiv_id_match = str(match_data.get("arxiv_id", "N/A"))

                db_text = (
                    self.dataset_texts[match_idx]
                    if match_idx < len(self.dataset_texts)
                    else "Text not available."
                )

                exact_copied_phrases = self._extract_exact_matches(chunks[query_idx], db_text)

                sources[arxiv_id_match]["title"] = str(match_data.get("title", "N/A"))
                sources[arxiv_id_match]["matches"].append(
                    {
                        "query_chunk_idx": query_idx,
                        "query_text": chunks[query_idx],
                        "db_chunk_idx": int(match_data.get("chunk_id", -1)),
                        "db_text": db_text,
                        "cosine_similarity": round(cosine_sim, 4),
                        "match_percentage": round(cosine_sim * 100, 2),
                        "exact_copied_phrases": exact_copied_phrases,
                        "db_source_type": match_data.get("source_type", "unknown"),
                    }
                )

                if not chunk_already_flagged:
                    plagiarized_words_weighted_sum += cosine_sim * chunk_word_count
                    unique_flagged_chunks.add(query_idx)
                    chunk_already_flagged = True

        global_plagiarism_score = (plagiarized_words_weighted_sum / total_words_in_doc) * 100

        # Filter and rank before building the final report
        filtered_sources = self._filter_and_rank_sources(sources)

        report: dict[str, Any] = {
            "file_name": file_path.name,
            "document_stats": {
                "total_words": total_words_in_doc,
                "total_chunks_analyzed": len(chunks),
            },
            "analysis_config": {
                "threshold_used": threshold,
                "metric": "Cosine Similarity",
                "embedding_model": "allenai/specter",
                "max_sources_reported": self.max_sources,
                "max_matches_per_source": self.max_matches_per_source,
            },
            "global_plagiarism_score_percent": round(global_plagiarism_score, 2),
            "total_suspicious_sources": len(sources),       # raw count before filtering
            "total_reported_sources": len(filtered_sources), # after filtering
            "total_flagged_chunks": len(unique_flagged_chunks),
            "sources": filtered_sources,
        }

        return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Antiplagiarism Engine CLI")
    parser.add_argument("--input", type=Path, required=True,
                        help="Path to the PDF, .tex, or .txt file to analyze")
    parser.add_argument("--output", type=Path, default=None,
                        help="Path to save the JSON report (e.g. report.json)")
    parser.add_argument("--arxiv-id", type=str, default=None,
                        help="Optional arXiv ID of the query document — enables LaTeX source fetching")
    parser.add_argument("--model-name", type=str, default="allenai/specter")
    parser.add_argument("--artifacts-dir", type=Path,
                        default=Path("backend/core/antiplagiator/artifacts"))
    parser.add_argument("--data-dir", type=Path,
                        default=Path("backend/core/antiplagiator/data/processed"))
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="Cosine similarity threshold (default: 0.85)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-sources", type=int, default=10,
                        help="Maximum number of sources to include in the report")
    parser.add_argument("--max-matches", type=int, default=5,
                        help="Maximum number of matches to show per source")
    parser.add_argument("--pretty", action="store_true",
                        help="Print / save JSON with indentation")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    engine = AntiplagiarismEngine(
        model_name=args.model_name,
        artifacts_dir=args.artifacts_dir,
        data_dir=args.data_dir,
        device=args.device,
        max_sources=args.max_sources,
        max_matches_per_source=args.max_matches,
    )

    LOGGER.info("Analyzing %s...", args.input.name)
    result = engine.analyze_document(
        args.input,
        threshold=args.threshold,
        top_k=args.top_k,
        arxiv_id=args.arxiv_id,
    )

    indent = 2 if args.pretty else None

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=indent, ensure_ascii=False)
        LOGGER.info("Report saved to %s", args.output.absolute())
    else:
        print(json.dumps(result, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()