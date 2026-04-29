from __future__ import annotations

import argparse
import difflib
import gzip
import io
import json
import logging
import pickle
import re
import sys
import tarfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import faiss
import fitz
import joblib
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from sentence_transformers import SentenceTransformer
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).parent))
from category_router import route

LOGGER = logging.getLogger("plagiarism_engine")

ARXIV_SRC_URL = "https://export.arxiv.org/src/{arxiv_id}"

DEFAULT_MODEL  = "BAAI/bge-m3"
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

CATEGORY_NAME_TO_CODE: dict[str, str] = {v: k for k, v in CATEGORY_CODE_TO_NAME.items()}

# ---------------------------------------------------------------------------
# Text normalisation — must be identical to 02_chunker.py
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
    text = re.sub(r'\\\"([aouAOU])', lambda m: m.group(1).translate(
        str.maketrans('aouAOU', 'äöüÄÖÜ')), text)
    text = re.sub(r'\\[a-zA-Z]+\*?\s*', ' ', text)
    text = re.sub(r'[{}\[\]$]', ' ', text)
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "SentinelEngine/4.0"})
    retry = Retry(
        total=3, backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


def resolve_device(preferred: str) -> str:
    if preferred in {"cpu", "cuda"}:
        return preferred
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AntiplagiarismEngine:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        artifacts_dir: Path = Path("backend/core/antiplagiator/artifacts"),
        data_dir: Path = Path("backend/core/antiplagiator/data/processed"),
        device: str = "auto",
        max_sources: int = 10,
        max_matches_per_source: int = 5,
        nprobe: int = DEFAULT_NPROBE,
        use_category_routing: bool = True,
        classifier_artifact: str = "category_classifier.pkl",
        confidence_threshold: float = 0.40,
        routing_top_k: int = 2,
        use_per_category_indexes: bool = False,
    ) -> None:
        self.artifacts_dir            = artifacts_dir
        self.data_dir                 = data_dir
        self.device                   = resolve_device(device)
        self._session                 = _build_session()
        self.max_sources              = max_sources
        self.max_matches_per_source   = max_matches_per_source
        self.nprobe                   = nprobe
        self.use_category_routing     = use_category_routing
        self.confidence_threshold     = confidence_threshold
        self.routing_top_k            = routing_top_k
        self.use_per_category_indexes = use_per_category_indexes

        LOGGER.info(
            "Initialising AntiplagiarismEngine (model=%s, device=%s)",
            model_name, self.device,
        )
        self.model = SentenceTransformer(model_name, device=self.device)

        # ── Global FAISS index ────────────────────────────────────────────
        index_path    = artifacts_dir / "faiss_document_index.bin"
        metadata_path = artifacts_dir / "faiss_metadata.pkl"
        dataset_path  = data_dir / "chunked_database.jsonl"

        if not index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {index_path}")
        if not metadata_path.exists():
            raise FileNotFoundError(f"FAISS metadata not found: {metadata_path}")

        LOGGER.info("Loading global FAISS index ...")
        self.index = faiss.read_index(str(index_path))
        if hasattr(self.index, "nprobe"):
            self.index.nprobe = nprobe

        with metadata_path.open("rb") as f:
            self.metadata: list[dict[str, Any]] = pickle.load(f)

        LOGGER.info("Loading dataset texts ...")
        self.dataset_texts = self._load_dataset_texts(dataset_path)

        # ── (arxiv_id, chunk_id) -> text lookup ───────────────────────────
        # Per-category metadata has text stripped; this bridges that gap
        # without requiring a FAISS rebuild.
        LOGGER.info("Building text lookup table ...")
        self._text_lookup: dict[tuple[str, int], str] = {}
        for text, meta in zip(self.dataset_texts, self.metadata):
            key = (str(meta.get("arxiv_id", "")), int(meta.get("chunk_id", -1)))
            self._text_lookup[key] = text
        LOGGER.info("Text lookup ready (%d entries)", len(self._text_lookup))

        # ── Per-category indexes ──────────────────────────────────────────
        self.cat_indexes:  dict[str, faiss.Index] = {}
        self.cat_metadata: dict[str, list[dict]]  = {}

        if use_per_category_indexes:
            self._load_per_category_indexes(artifacts_dir / "category_indexes")

        # ── Classifier ────────────────────────────────────────────────────
        self.clf = None
        if use_category_routing:
            clf_path = artifacts_dir / classifier_artifact
            if clf_path.exists():
                artifact = joblib.load(clf_path)
                self.clf = artifact["classifier"]
                LOGGER.info("Classifier loaded — %d classes", len(artifact["labels"]))
            else:
                LOGGER.warning(
                    "Classifier artifact not found at %s — routing disabled", clf_path
                )
                self.use_category_routing = False

        LOGGER.info("Engine ready.")

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_dataset_texts(self, jsonl_path: Path) -> list[str]:
        texts: list[str] = []
        if not jsonl_path.exists():
            LOGGER.warning("Dataset JSONL not found: %s", jsonl_path)
            return texts
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    texts.append(str(json.loads(line).get("text", "")))
        return texts

    def _load_per_category_indexes(self, cat_dir: Path) -> None:
        """
        Load per-category FAISS indexes.
        Registers each index under its file key, its arXiv code, AND its
        human-readable name so routing always finds a match.
        """
        if not cat_dir.exists():
            LOGGER.warning("Per-category index dir not found: %s", cat_dir)
            return

        for index_file in cat_dir.glob("faiss_*.bin"):
            meta_file = index_file.with_name(f"{index_file.stem}_meta.pkl")
            if not meta_file.exists():
                continue

            idx = faiss.read_index(str(index_file))
            if hasattr(idx, "nprobe"):
                idx.nprobe = self.nprobe

            with meta_file.open("rb") as f:
                meta = pickle.load(f)

            file_key = index_file.stem[len("faiss_"):]          # e.g. "nucl-ex"
            name_key = CATEGORY_CODE_TO_NAME.get(file_key, file_key)  # e.g. "Nuclear Experiment"
            safe_key = file_key.replace("-", "_").replace(".", "_")    # e.g. "nucl_ex"

            for key in {file_key, name_key, safe_key}:
                self.cat_indexes[key]  = idx
                self.cat_metadata[key] = meta

            LOGGER.info(
                "Loaded per-category index: %s → '%s' (%d vectors)",
                file_key, name_key, idx.ntotal,
            )

    # ------------------------------------------------------------------
    # Embedding with LRU cache
    # ------------------------------------------------------------------

    @lru_cache(maxsize=256)
    def _encode_text_cached(self, text: str) -> np.ndarray:
        return self.model.encode(
            [text], convert_to_numpy=True, normalize_embeddings=True
        )[0]

    def _encode_chunks(self, chunks: list[str]) -> np.ndarray:
        return np.vstack([self._encode_text_cached(c) for c in chunks])

    # ------------------------------------------------------------------
    # Category routing
    # ------------------------------------------------------------------

    def _get_allowed_categories(
        self, query_embedding: np.ndarray
    ) -> list[str] | None:
        if not self.use_category_routing or self.clf is None:
            return None
        categories, _ = route(
            self.clf,
            query_embedding,
            confidence_threshold=self.confidence_threshold,
            top_k=self.routing_top_k,
        )
        return categories

    # ------------------------------------------------------------------
    # FAISS search helpers
    # ------------------------------------------------------------------

    def _search_global(
        self,
        query_vectors: np.ndarray,
        top_k: int,
        allowed_categories: list[str] | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        similarities, indices = self.index.search(query_vectors, k=top_k)
        if allowed_categories is None:
            return similarities, indices

        # Accept both code and name forms in the whitelist
        allowed_codes: set[str] = set()
        for cat in allowed_categories:
            allowed_codes.add(cat)
            allowed_codes.add(CATEGORY_NAME_TO_CODE.get(cat, cat))
            allowed_codes.add(CATEGORY_CODE_TO_NAME.get(cat, cat))

        filtered_sim = np.full_like(similarities, -1.0)
        filtered_idx = np.full_like(indices, -1)
        for row in range(len(indices)):
            write_col = 0
            for col in range(indices.shape[1]):
                idx = int(indices[row, col])
                if idx < 0 or idx >= len(self.metadata):
                    continue
                cat = self.metadata[idx].get("top_category", "")
                if cat in allowed_codes:
                    filtered_sim[row, write_col] = similarities[row, col]
                    filtered_idx[row, write_col] = idx
                    write_col += 1
                    if write_col >= top_k:
                        break
        return filtered_sim, filtered_idx

    def _search_per_category(
        self,
        query_vectors: np.ndarray,
        top_k: int,
        allowed_categories: list[str],
    ) -> tuple[list[list[float]], list[list[dict]]]:
        n_queries  = len(query_vectors)
        all_scores: list[list[float]] = [[] for _ in range(n_queries)]
        all_meta:   list[list[dict]]  = [[] for _ in range(n_queries)]

        for cat in allowed_categories:
            code = CATEGORY_NAME_TO_CODE.get(cat, cat)
            safe = code.replace("-", "_").replace(".", "_").replace("/", "_")
            name = CATEGORY_CODE_TO_NAME.get(code, cat)

            cat_idx = (
                self.cat_indexes.get(name)
                or self.cat_indexes.get(code)
                or self.cat_indexes.get(safe)
                or self.cat_indexes.get(cat)
            )
            cat_meta = (
                self.cat_metadata.get(name)
                or self.cat_metadata.get(code)
                or self.cat_metadata.get(safe)
                or self.cat_metadata.get(cat)
            )

            if cat_idx is None:
                LOGGER.debug(
                    "No per-category index for '%s' (tried: %s / %s / %s) — skipping",
                    cat, name, code, safe,
                )
                continue

            LOGGER.debug("Searching per-category index '%s' for '%s'", code, cat)
            sims, idxs = cat_idx.search(query_vectors, k=top_k)

            for row in range(n_queries):
                for col in range(top_k):
                    raw_idx = int(idxs[row, col])
                    if raw_idx < 0 or raw_idx >= len(cat_meta):
                        continue
                    all_scores[row].append(float(sims[row, col]))
                    all_meta[row].append(cat_meta[raw_idx])

        return all_scores, all_meta

    def _resolve_db_text(self, match_data: dict) -> str:
        """
        Retrieve chunk text for a metadata record.
        Per-category metadata has text stripped; falls back to global lookup.
        """
        text = match_data.get("text", "")
        if text:
            return text
        key = (
            str(match_data.get("arxiv_id", "")),
            int(match_data.get("chunk_id", -1)),
        )
        return self._text_lookup.get(key, "Text not available.")

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    def _fetch_latex_source(self, arxiv_id: str, timeout: int = 30) -> str | None:
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
                return f.read().decode("utf-8", errors="replace") if f else None
        except tarfile.TarError:
            pass
        try:
            return gzip.decompress(content).decode("utf-8", errors="replace")
        except Exception:
            return None

    def _strip_latex_structure(self, latex: str) -> str:
        latex = re.sub(r'%[^\n]*', ' ', latex)
        doc_start = re.search(r'\\begin\{document\}', latex)
        if doc_start:
            latex = latex[doc_start.end():]
        bib = re.search(r'\\begin\{thebibliography\}', latex, re.IGNORECASE)
        if bib:
            latex = latex[:bib.start()]
        for cmd in (
            "textbf", "textit", "emph", "text", "mathrm", "mathbf",
            "mathit", "mathcal", "mathbb", "mathsf", "operatorname",
            "title", "author", "section", "subsection", "subsubsection",
            "paragraph", "caption", "label", "ref", "cite",
        ):
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
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        raw_text = ""
        if arxiv_id:
            latex = self._fetch_latex_source(arxiv_id)
            if latex and len(latex.split()) >= 20:
                raw_text = self._strip_latex_structure(latex)
        if not raw_text and file_path.suffix.lower() == ".tex":
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                raw_text = self._strip_latex_structure(f.read())
        if not raw_text and file_path.suffix.lower() == ".pdf":
            with fitz.open(file_path) as doc:
                raw_text = " ".join(p.get_text("text") for p in doc)
            raw_text = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', raw_text)
            raw_text = re.sub(r'\s+', ' ', raw_text).strip()
            m = re.search(r"\b(References|Bibliography)\b", raw_text, re.IGNORECASE)
            if m and m.start() > len(raw_text) * 0.75:
                raw_text = raw_text[: m.start()]
        if not raw_text:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                raw_text = re.sub(r'\s+', ' ', f.read()).strip()
        normalized = normalize_text_for_fingerprint(raw_text)
        words = normalized.split()
        step  = chunk_size - overlap
        return [
            " ".join(words[i: i + chunk_size])
            for i in range(0, len(words), step)
            if len(words[i: i + chunk_size]) >= 20
        ]

    def _extract_exact_matches(
        self, query_text: str, db_text: str, min_words: int = 6
    ) -> list[str]:
        matcher = difflib.SequenceMatcher(None, query_text, db_text, autojunk=False)
        exact_phrases: set[str] = set()
        for match in matcher.get_matching_blocks():
            phrase = query_text[match.a: match.a + match.size].strip()
            if len(phrase.split()) >= min_words:
                exact_phrases.add(phrase)
        return list(exact_phrases)

    def _filter_and_rank_sources(
        self, sources: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        for data in sources.values():
            data["matches"] = sorted(
                data["matches"],
                key=lambda m: m["cosine_similarity"],
                reverse=True,
            )[: self.max_matches_per_source]

        sources_with_exact = {
            aid: d for aid, d in sources.items()
            if any(len(m["exact_copied_phrases"]) > 0 for m in d["matches"])
        }
        sources_to_rank = sources_with_exact if sources_with_exact else sources
        sorted_sources = sorted(
            sources_to_rank.items(),
            key=lambda item: len(item[1]["matches"]),
            reverse=True,
        )[: self.max_sources]

        result = []
        for src_id, data in sorted_sources:
            avg = (
                sum(m["match_percentage"] for m in data["matches"])
                / len(data["matches"])
            )
            result.append({
                "arxiv_id":                   src_id,
                "title":                      data["title"],
                "match_count":                len(data["matches"]),
                "average_similarity_percent": round(avg, 2),
                "has_exact_copies":           any(
                    len(m["exact_copied_phrases"]) > 0 for m in data["matches"]
                ),
                "matches": data["matches"],
            })
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
        chunks = self._read_and_chunk_file(file_path, arxiv_id=arxiv_id)
        if not chunks:
            return {"error": "No valid text could be extracted."}

        total_words = sum(len(c.split()) for c in chunks)
        if total_words == 0:
            return {"error": "Document is empty."}

        query_vectors = self._encode_chunks(chunks).astype("float32")

        doc_embedding      = query_vectors[0]
        allowed_categories = self._get_allowed_categories(doc_embedding)

        sources: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"title": "", "matches": []}
        )
        plagiarized_weighted = 0.0
        flagged_chunks: set[int] = set()

        if self.use_per_category_indexes and allowed_categories and self.cat_indexes:
            # Strategy A: per-category sub-indexes
            all_scores, all_meta_rows = self._search_per_category(
                query_vectors, top_k, allowed_categories
            )
            for query_idx, (score_row, meta_row) in enumerate(
                zip(all_scores, all_meta_rows)
            ):
                chunk_word_count = len(chunks[query_idx].split())
                chunk_flagged    = False
                for cosine_sim_raw, match_data in zip(score_row, meta_row):
                    cosine_sim = max(0.0, min(1.0, cosine_sim_raw))
                    if cosine_sim < threshold:
                        continue
                    aid     = str(match_data.get("arxiv_id", "N/A"))
                    db_text = self._resolve_db_text(match_data)
                    sources[aid]["title"] = str(match_data.get("title", "N/A"))
                    sources[aid]["matches"].append(
                        self._build_match(
                            query_idx, chunks[query_idx], match_data, db_text, cosine_sim
                        )
                    )
                    if not chunk_flagged:
                        plagiarized_weighted += cosine_sim * chunk_word_count
                        flagged_chunks.add(query_idx)
                        chunk_flagged = True
        else:
            # Strategy B: global index + optional post-filter
            similarities, indices = self._search_global(
                query_vectors, top_k, allowed_categories
            )
            for query_idx, (score_row, idx_row) in enumerate(
                zip(similarities, indices)
            ):
                chunk_word_count = len(chunks[query_idx].split())
                chunk_flagged    = False
                for i in range(top_k):
                    cosine_sim = max(0.0, min(1.0, float(score_row[i])))
                    if cosine_sim < threshold:
                        continue
                    match_idx = int(idx_row[i])
                    if match_idx < 0 or match_idx >= len(self.metadata):
                        continue
                    match_data = self.metadata[match_idx]
                    db_text    = (
                        self.dataset_texts[match_idx]
                        if match_idx < len(self.dataset_texts)
                        else "Text not available."
                    )
                    aid = str(match_data.get("arxiv_id", "N/A"))
                    sources[aid]["title"] = str(match_data.get("title", "N/A"))
                    sources[aid]["matches"].append(
                        self._build_match(
                            query_idx, chunks[query_idx], match_data, db_text, cosine_sim
                        )
                    )
                    if not chunk_flagged:
                        plagiarized_weighted += cosine_sim * chunk_word_count
                        flagged_chunks.add(query_idx)
                        chunk_flagged = True

        global_score     = (plagiarized_weighted / total_words) * 100
        filtered_sources = self._filter_and_rank_sources(sources)

        return {
            "file_name": file_path.name,
            "document_stats": {
                "total_words":           total_words,
                "total_chunks_analyzed": len(chunks),
            },
            "analysis_config": {
                "threshold_used":  threshold,
                "metric":          "Cosine Similarity (IVFFlat)",
                "embedding_model": DEFAULT_MODEL,
                "category_routing": {
                    "enabled":   self.use_category_routing,
                    "routed_to": allowed_categories,
                    "strategy":  (
                        "per_category"
                        if self.use_per_category_indexes
                        else "post_filter"
                    ),
                },
                "max_sources_reported":   self.max_sources,
                "max_matches_per_source": self.max_matches_per_source,
            },
            "global_plagiarism_score_percent": round(global_score, 2),
            "total_suspicious_sources":        len(sources),
            "total_reported_sources":          len(filtered_sources),
            "total_flagged_chunks":            len(flagged_chunks),
            "sources":                         filtered_sources,
        }

    def _build_match(
        self,
        query_idx: int,
        query_chunk: str,
        match_data: dict,
        db_text: str,
        cosine_sim: float,
    ) -> dict[str, Any]:
        return {
            "query_chunk_idx":      query_idx,
            "query_text":           query_chunk,
            "db_chunk_idx":         int(match_data.get("chunk_id", -1)),
            "db_text":              db_text,
            "cosine_similarity":    round(cosine_sim, 4),
            "match_percentage":     round(cosine_sim * 100, 2),
            "exact_copied_phrases": self._extract_exact_matches(query_chunk, db_text),
            "db_source_type":       match_data.get("source_type", "unknown"),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Antiplagiarism Engine CLI")
    parser.add_argument("--input",         type=Path, required=True)
    parser.add_argument("--output",        type=Path, default=None)
    parser.add_argument("--arxiv-id",      type=str,  default=None)
    parser.add_argument("--model-name",    type=str,  default=DEFAULT_MODEL)
    parser.add_argument(
        "--artifacts-dir", type=Path,
        default=Path("backend/core/antiplagiator/artifacts"),
    )
    parser.add_argument(
        "--data-dir", type=Path,
        default=Path("backend/core/antiplagiator/data/processed"),
    )
    parser.add_argument(
        "--device", type=str, default="auto",
        choices=["auto", "cpu", "cuda"],
    )
    parser.add_argument("--threshold",   type=float, default=0.85)
    parser.add_argument("--top-k",       type=int,   default=5)
    parser.add_argument("--nprobe",      type=int,   default=DEFAULT_NPROBE)
    parser.add_argument("--max-sources", type=int,   default=10)
    parser.add_argument("--max-matches", type=int,   default=5)
    parser.add_argument(
        "--no-routing", action="store_true",
        help="Disable category routing — always search globally",
    )
    parser.add_argument(
        "--per-category-indexes", action="store_true",
        help="Use per-category FAISS sub-indexes instead of global post-filter",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    engine = AntiplagiarismEngine(
        model_name=args.model_name,
        artifacts_dir=args.artifacts_dir,
        data_dir=args.data_dir,
        device=args.device,
        max_sources=args.max_sources,
        max_matches_per_source=args.max_matches,
        nprobe=args.nprobe,
        use_category_routing=not args.no_routing,
        use_per_category_indexes=args.per_category_indexes,
    )

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