from __future__ import annotations

import argparse
import difflib
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import faiss
import joblib
import numpy as np
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent))

from category_router import route
from engine_modules.constants import (
    CATEGORY_CODE_TO_NAME,
    CATEGORY_NAME_TO_CODE,
    DEFAULT_MODEL,
    DEFAULT_NPROBE,
)
from engine_modules.index_loader import (
    build_text_lookup,
    load_dataset_texts,
    load_global_index,
    load_per_category_indexes,
)
from engine_modules.text_extractor import TextExtractor
from engine_modules.utils import build_session, resolve_device

LOGGER = logging.getLogger("plagiarism_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_WORDS = 50_000
ROUTING_SAMPLE_SIZE = 8
HIGH_CONFIDENCE_THRESHOLD = 0.90
MIN_EXACT_PHRASE_CHARS = 50
PARAPHRASE_RETRIEVAL_THRESHOLD = 0.70
PARAPHRASE_CROSS_SCORE_THRESHOLD = 0.0
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

def _severity(similarity: float) -> str:
    if similarity >= 0.95:
        return "identical"
    if similarity >= 0.85:
        return "highly_similar"
    return "paraphrased"


def _normalize_cross_score(logit: float) -> float:
    return 1.0 / (1.0 + math.exp(-logit))


@dataclass
class ChunkMatch:
    query_chunk_idx: int
    query_text: str
    db_chunk_idx: int
    db_text: str
    cosine_similarity: float
    match_percentage: float
    exact_copied_phrases: list[str]
    db_source_type: str
    severity: str
    detection: str = "exact"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_chunk_idx":      self.query_chunk_idx,
            "query_text":           self.query_text,
            "db_chunk_idx":         self.db_chunk_idx,
            "db_text":              self.db_text,
            "cosine_similarity":    self.cosine_similarity,
            "match_percentage":     self.match_percentage,
            "exact_copied_phrases": self.exact_copied_phrases,
            "db_source_type":       self.db_source_type,
            "severity":             self.severity,
            "detection":            self.detection,
        }


@dataclass
class SourceResult:
    arxiv_id: str
    title: str
    matches: list[ChunkMatch] = field(default_factory=list)
    flagged_word_count: int = 0

    @property
    def has_exact_copies(self) -> bool:
        return any(m.exact_copied_phrases for m in self.matches)

    @property
    def average_similarity(self) -> float:
        if not self.matches:
            return 0.0
        return sum(m.match_percentage for m in self.matches) / len(self.matches)

    def to_dict(self, total_words: int) -> dict[str, Any]:
        contribution = (
            round(self.flagged_word_count / total_words * 100, 2)
            if total_words > 0 else 0.0
        )
        return {
            "arxiv_id":                   self.arxiv_id,
            "title":                      self.title,
            "match_count":                len(self.matches),
            "average_similarity_percent": round(self.average_similarity, 2),
            "has_exact_copies":           self.has_exact_copies,
            "score_contribution_percent": contribution,
            "matches":                    [m.to_dict() for m in self.matches],
        }


@dataclass
class RoutingDecision:
    enabled: bool
    categories: list[str] | None
    confidence: float
    strategy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled":    self.enabled,
            "categories": self.categories,
            "confidence": round(self.confidence, 3),
            "strategy":   self.strategy,
        }


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
        use_reranker: bool = False,
        reranker_model: str = DEFAULT_RERANKER_MODEL,
    ) -> None:
        self.max_sources = max_sources
        self.max_matches_per_source = max_matches_per_source
        self.nprobe = nprobe
        self.use_category_routing = use_category_routing
        self.confidence_threshold = confidence_threshold
        self.routing_top_k = routing_top_k
        self.use_per_category_indexes = use_per_category_indexes

        self.is_ready = False
        self.init_error: str | None = None

        resolved_device = resolve_device(device)
        LOGGER.info("Initialising engine (model=%s, device=%s)", model_name, resolved_device)

        try:
            self._setup_modules(model_name, resolved_device)
            self._setup_indexes(artifacts_dir, data_dir, nprobe)
            self._setup_classifier(artifacts_dir, classifier_artifact, use_category_routing)
            self._setup_reranker(reranker_model, resolved_device, use_reranker)
            self.is_ready = True
            LOGGER.info("Engine ready.")
        except Exception as exc:
            self.init_error = str(exc)
            LOGGER.error("Engine failed to initialise: %s", exc)

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _setup_modules(self, model_name: str, device: str) -> None:
        self._session = build_session()
        self._extractor = TextExtractor(self._session)
        LOGGER.info("Loading SentenceTransformer: %s", model_name)
        self._model = SentenceTransformer(model_name, device=device)

    def _setup_indexes(self, artifacts_dir: Path, data_dir: Path, nprobe: int) -> None:
        """
        Load FAISS index — either from the Modal remote server (when
        FAISS_REMOTE_URL is set in the environment) or from local disk.
        """
        remote_url = os.getenv("FAISS_REMOTE_URL", "").strip()

        if remote_url:
            # ── Remote mode: delegate all FAISS search to Modal ──────────────
            LOGGER.info("FAISS_REMOTE_URL detected — using Modal RemoteIndex")
            from engine_modules.remote_index import RemoteIndex
            remote = RemoteIndex.from_env()
            self.index         = remote
            self.metadata      = remote.metadata   # grows lazily per search
            self.dataset_texts = []
            self._text_lookup  = {}
            self.cat_indexes   = {}
            self.cat_metadata  = {}
            LOGGER.info("RemoteIndex ready -> %s", remote_url)
        else:
            # ── Local mode: original behaviour ───────────────────────────────
            LOGGER.info("No FAISS_REMOTE_URL — using local FAISS index")
            self.index, self.metadata = load_global_index(artifacts_dir, nprobe)

            dataset_path = data_dir / "chunked_database.jsonl"
            self.dataset_texts = load_dataset_texts(dataset_path)
            self._text_lookup = build_text_lookup(self.dataset_texts, self.metadata)

            self.cat_indexes: dict[str, faiss.Index] = {}
            self.cat_metadata: dict[str, list[dict]] = {}
            if self.use_per_category_indexes:
                self.cat_indexes, self.cat_metadata = load_per_category_indexes(
                    artifacts_dir / "category_indexes",
                    nprobe,
                    CATEGORY_CODE_TO_NAME,
                )

    def _setup_classifier(
        self, artifacts_dir: Path, artifact_name: str, enabled: bool
    ) -> None:
        self.clf = None
        if not enabled:
            return
        clf_path = artifacts_dir / artifact_name
        if clf_path.exists():
            artifact = joblib.load(clf_path)
            self.clf = artifact["classifier"]
            LOGGER.info("Classifier loaded — %d classes", len(artifact["labels"]))
        else:
            LOGGER.warning("Classifier not found at %s — routing disabled", clf_path)
            self.use_category_routing = False

    def _setup_reranker(
        self, model_name: str, device: str, enabled: bool
    ) -> None:
        self._reranker = None
        if not enabled:
            return
        try:
            from engine_modules.reranker import Reranker
            self._reranker = Reranker(model_name=model_name, device=device)
            LOGGER.info("Cross-encoder reranker ready: %s", model_name)
        except ImportError:
            LOGGER.warning(
                "engine/reranker.py not found or CrossEncoder unavailable — "
                "paraphrase_mode will have no effect."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_document(
        self,
        file_path: Path,
        threshold: float = 0.85,
        top_k: int = 5,
        arxiv_id: str | None = None,
        paraphrase_mode: bool = False,
    ) -> dict[str, Any]:
        if not self.is_ready:
            return {"error": f"Engine not ready: {self.init_error}"}

        active_paraphrase = paraphrase_mode and self._reranker is not None
        timings: dict[str, float] = {}

        # ── 1. Extraction ──
        t0 = time.monotonic()
        chunks, full_text, display_text = self._extractor.read_and_chunk(file_path, arxiv_id=arxiv_id)
        if not chunks:
            return {
                "file_name": file_path.name,
                "global_plagiarism_score_percent": 0.0,
                "total_reported_sources": 0,
                "document_stats": {"total_words": 0, "total_chunks_analyzed": 0},
                "sources": [],
                "error": "No valid text could be extracted."
            }

        chunks = _truncate_chunks(chunks, MAX_WORDS)
        chunks = _filter_chunks(chunks)
        total_words = sum(len(c.split()) for c in chunks)
        timings["extraction_s"] = round(time.monotonic() - t0, 3)

        # ── 2. Encoding ──
        t1 = time.monotonic()
        query_vectors = self._encode_batch(chunks)
        timings["encoding_s"] = round(time.monotonic() - t1, 3)

        # ── 3. Routing ──
        routing = self._decide_routing(query_vectors)

        # ── 4. Search ──
        retrieval_threshold = (
            PARAPHRASE_RETRIEVAL_THRESHOLD if active_paraphrase else threshold
        )

        t2 = time.monotonic()
        sources, flagged_chunk_map, counted_word_positions = self._run_search(
            chunks, query_vectors,
            retrieval_threshold=retrieval_threshold,
            flag_threshold=threshold,
            top_k=top_k,
            routing=routing,
            self_arxiv_id=arxiv_id,
            paraphrase_mode=active_paraphrase,
        )
        timings["search_s"] = round(time.monotonic() - t2, 3)

        # ── 5. Ranking and Scoring ──
        t3 = time.monotonic()
        ranked_sources = self._rank_and_trim_sources(sources)

        flagged_words = len(counted_word_positions)

        if total_words > 0:
            word_coverage = flagged_words / total_words
            if ranked_sources:
                worst_source_words = max(s.flagged_word_count for s in ranked_sources)
                source_weighted = worst_source_words / total_words
            else:
                source_weighted = 0.0
        else:
            word_coverage = 0.0
            source_weighted = 0.0

        timings["ranking_s"] = round(time.monotonic() - t3, 3)
        timings["total_s"] = round(sum(timings.values()), 3)

        return {
            "file_name": file_path.name,
            "global_plagiarism_score_percent": round(source_weighted * 100, 2),
            "total_reported_sources": len(ranked_sources),
            "total_suspicious_sources": len(sources),
            "full_text": full_text,           # normalized (used for matching)
            "display_text": display_text,     # original extracted text (used for display)
            "document_stats": {
                "total_words": total_words,
                "total_chunks_analyzed": len(chunks),
            },
            "flagged_chunks": _format_flagged_chunks(flagged_chunk_map),
            "sources": [s.to_dict(total_words) for s in ranked_sources],
            "analysis_config": {
                "routing": routing.to_dict(),
                "threshold_used": threshold,
                "top_k": top_k,
                "paraphrase_mode": active_paraphrase,
                "embedding_model": DEFAULT_MODEL,
                "timing": timings,
            },
        }

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def _encode_batch(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        ).astype("float32")

    # ------------------------------------------------------------------
    # Category routing
    # ------------------------------------------------------------------

    def _decide_routing(self, query_vectors: np.ndarray) -> RoutingDecision:
        if not self.use_category_routing or self.clf is None:
            return RoutingDecision(
                enabled=False, categories=None, confidence=0.0, strategy="global"
            )

        sample_indices = _spread_sample(len(query_vectors), ROUTING_SAMPLE_SIZE)
        sample_vectors = query_vectors[sample_indices]

        category_votes: dict[str, float] = defaultdict(float)
        total_confidence = 0.0

        for vec in sample_vectors:
            categories, confidence = route(
                self.clf,
                vec,
                confidence_threshold=self.confidence_threshold,
                top_k=self.routing_top_k,
            )
            total_confidence += confidence
            if categories:
                cats_to_count = (
                    categories[:1]
                    if confidence > HIGH_CONFIDENCE_THRESHOLD
                    else categories
                )
                for cat in cats_to_count:
                    category_votes[str(cat)] += confidence

        avg_confidence = total_confidence / len(sample_vectors)

        if not category_votes:
            return RoutingDecision(
                enabled=True, categories=None,
                confidence=avg_confidence, strategy="global"
            )

        max_cats = 1 if avg_confidence > HIGH_CONFIDENCE_THRESHOLD else self.routing_top_k
        top_categories = [str(c) for c in sorted(
            category_votes, key=category_votes.__getitem__, reverse=True
        )[:max_cats]]

        strategy = (
            "per_category"
            if self.use_per_category_indexes and self.cat_indexes
            else "post_filter"
        )
        return RoutingDecision(
            enabled=True, categories=top_categories,
            confidence=avg_confidence, strategy=strategy,
        )

    # ------------------------------------------------------------------
    # Search orchestration
    # ------------------------------------------------------------------

    def _run_search(
        self,
        chunks: list[str],
        query_vectors: np.ndarray,
        retrieval_threshold: float,
        flag_threshold: float,
        top_k: int,
        routing: RoutingDecision,
        self_arxiv_id: str | None,
        paraphrase_mode: bool,
    ) -> tuple[dict[str, SourceResult], dict[int, dict], set[int]]:
        sources: dict[str, SourceResult] = {}
        flagged_chunk_map: dict[int, dict] = {}
        counted_word_positions: set[int] = set()

        word_offset = 0
        chunk_word_counts = [len(c.split()) for c in chunks]

        use_per_cat = (
            self.use_per_category_indexes
            and routing.categories
            and self.cat_indexes
        )

        if use_per_cat:
            score_rows, meta_rows = self._search_per_category_parallel(
                query_vectors, top_k, routing.categories
            )
            for chunk_idx, (scores, metas) in enumerate(zip(score_rows, meta_rows)):
                chunk_words = chunk_word_counts[chunk_idx]
                flagged_info = self._process_per_category_hits(
                    chunk_idx, chunks[chunk_idx], scores, metas,
                    retrieval_threshold, flag_threshold,
                    word_offset, chunk_words,
                    sources, counted_word_positions, self_arxiv_id,
                    paraphrase_mode,
                )
                if flagged_info:
                    flagged_chunk_map[chunk_idx] = flagged_info
                word_offset += chunk_words
        else:
            # Pass original text chunks to RemoteIndex before search
            # so it can send them to Modal for encoding (no-op for local FAISS)
            if hasattr(self.index, "set_query_texts"):
                self.index.set_query_texts(chunks)

            similarities, db_indices = self._search_global(
                query_vectors, top_k, routing.categories
            )
            for chunk_idx, (scores, indices) in enumerate(zip(similarities, db_indices)):
                chunk_words = chunk_word_counts[chunk_idx]
                flagged_info = self._process_global_hits(
                    chunk_idx, chunks[chunk_idx], scores, indices,
                    retrieval_threshold, flag_threshold, top_k,
                    word_offset, chunk_words,
                    sources, counted_word_positions, self_arxiv_id,
                    paraphrase_mode,
                )
                if flagged_info:
                    flagged_chunk_map[chunk_idx] = flagged_info
                word_offset += chunk_words

        return sources, flagged_chunk_map, counted_word_positions

    def _process_per_category_hits(
        self,
        chunk_idx: int,
        chunk_text: str,
        scores: list[float],
        metas: list[dict],
        retrieval_threshold: float,
        flag_threshold: float,
        word_offset: int,
        chunk_words: int,
        sources: dict[str, SourceResult],
        counted_positions: set[int],
        self_arxiv_id: str | None,
        paraphrase_mode: bool,
    ) -> dict | None:
        candidates: list[tuple[float, dict, str]] = []
        for raw_score, meta in zip(scores, metas):
            if self_arxiv_id and meta.get("arxiv_id") == self_arxiv_id:
                continue
            similarity = _clamp(raw_score)
            if similarity < retrieval_threshold:
                continue
            db_text = self._resolve_db_text(meta)
            candidates.append((similarity, meta, db_text))

        if not candidates:
            return None

        if paraphrase_mode:
            return self._apply_reranker(
                chunk_idx, chunk_text, candidates,
                word_offset, chunk_words, sources, counted_positions,
            )
        else:
            return self._apply_flag_threshold(
                chunk_idx, chunk_text, candidates, flag_threshold,
                word_offset, chunk_words, sources, counted_positions,
            )

    def _process_global_hits(
        self,
        chunk_idx: int,
        chunk_text: str,
        scores: np.ndarray,
        db_indices: np.ndarray,
        retrieval_threshold: float,
        flag_threshold: float,
        top_k: int,
        word_offset: int,
        chunk_words: int,
        sources: dict[str, SourceResult],
        counted_positions: set[int],
        self_arxiv_id: str | None,
        paraphrase_mode: bool,
    ) -> dict | None:
        candidates: list[tuple[float, dict, str]] = []
        for i in range(top_k):
            similarity = _clamp(float(scores[i]))
            if similarity < retrieval_threshold:
                continue
            db_idx = int(db_indices[i])
            if db_idx < 0 or db_idx >= len(self.metadata):
                continue
            meta = self.metadata[db_idx]
            if self_arxiv_id and meta.get("arxiv_id") == self_arxiv_id:
                continue

            # Remote mode: db_text comes embedded in metadata from Modal response
            # Local mode: look it up in dataset_texts
            db_text = meta.get("text", "")
            if not db_text:
                db_text = (
                    self.dataset_texts[db_idx]
                    if self.dataset_texts and db_idx < len(self.dataset_texts)
                    else "Text not available."
                )
            candidates.append((similarity, meta, db_text))

        if not candidates:
            return None

        if paraphrase_mode:
            return self._apply_reranker(
                chunk_idx, chunk_text, candidates,
                word_offset, chunk_words, sources, counted_positions,
            )
        else:
            return self._apply_flag_threshold(
                chunk_idx, chunk_text, candidates, flag_threshold,
                word_offset, chunk_words, sources, counted_positions,
            )

    # ------------------------------------------------------------------
    # Hit processing strategies
    # ------------------------------------------------------------------

    def _apply_flag_threshold(
        self,
        chunk_idx: int,
        chunk_text: str,
        candidates: list[tuple[float, dict, str]],
        flag_threshold: float,
        word_offset: int,
        chunk_words: int,
        sources: dict[str, SourceResult],
        counted_positions: set[int],
    ) -> dict | None:
        best_similarity = 0.0
        best_match_info: dict | None = None

        for similarity, meta, db_text in candidates:
            if similarity < flag_threshold:
                continue

            arxiv_id = meta.get("arxiv_id", "N/A")
            match = self._build_match(
                chunk_idx, chunk_text, meta, db_text, similarity,
                detection="exact",
            )
            source = sources.setdefault(
                arxiv_id, SourceResult(arxiv_id, meta.get("title", "N/A"))
            )
            source.matches.append(match)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match_info = {
                    "text":         chunk_text[:300],
                    "top_match":    db_text[:300],
                    "similarity":   round(similarity * 100, 2),
                    "source_arxiv": arxiv_id,
                    "severity":     _severity(similarity),
                    "detection":    "exact",
                }

        if best_similarity > 0:
            self._account_flagged_words(
                word_offset, chunk_words, counted_positions,
                best_match_info["source_arxiv"], sources,
            )
            return best_match_info
        return None

    def _apply_reranker(
        self,
        chunk_idx: int,
        chunk_text: str,
        candidates: list[tuple[float, dict, str]],
        word_offset: int,
        chunk_words: int,
        sources: dict[str, SourceResult],
        counted_positions: set[int],
    ) -> dict | None:
        candidate_texts = [db_text for _, _, db_text in candidates]
        meta_by_text    = {db_text: meta for _, meta, db_text in candidates}

        rerank_results = self._reranker.rerank(
            query=chunk_text,
            candidates=candidate_texts,
            threshold=PARAPHRASE_CROSS_SCORE_THRESHOLD,
        )

        best_score: float = -999.0
        best_match_info: dict | None = None

        for result in rerank_results:
            if not result.is_paraphrase:
                continue

            meta = meta_by_text.get(result.candidate_text)
            if meta is None:
                continue

            normalised = _normalize_cross_score(result.cross_score)
            arxiv_id   = meta.get("arxiv_id", "N/A")

            match = self._build_match(
                chunk_idx, chunk_text, meta, result.candidate_text, normalised,
                detection="paraphrase",
            )
            source = sources.setdefault(
                arxiv_id, SourceResult(arxiv_id, meta.get("title", "N/A"))
            )
            source.matches.append(match)

            if result.cross_score > best_score:
                best_score = result.cross_score
                best_match_info = {
                    "text":         chunk_text[:300],
                    "top_match":    result.candidate_text[:300],
                    "similarity":   round(normalised * 100, 2),
                    "source_arxiv": arxiv_id,
                    "severity":     _severity(normalised),
                    "detection":    "paraphrase",
                }

        if best_match_info is not None:
            self._account_flagged_words(
                word_offset, chunk_words, counted_positions,
                best_match_info["source_arxiv"], sources,
            )
            return best_match_info
        return None

    def _account_flagged_words(
        self,
        word_offset: int,
        chunk_words: int,
        counted_positions: set[int],
        best_source_id: str,
        sources: dict[str, SourceResult],
    ) -> None:
        chunk_positions = set(range(word_offset, word_offset + chunk_words))
        new_flagged_positions = chunk_positions - counted_positions
        counted_positions.update(chunk_positions)

        if best_source_id in sources:
            sources[best_source_id].flagged_word_count += len(new_flagged_positions)

    # ------------------------------------------------------------------
    # FAISS search strategies
    # ------------------------------------------------------------------

    def _search_global(
        self,
        query_vectors: np.ndarray,
        top_k: int,
        categories: list[str] | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Search FAISS index and return real similarity scores."""
        similarities, indices = self.index.search(query_vectors, k=top_k)
        return similarities, indices

    def _filter_by_category(
        self,
        similarities: np.ndarray,
        indices: np.ndarray,
        top_k: int,
        allowed_categories: list[str],
    ) -> tuple[np.ndarray, np.ndarray]:
        allowed = _expand_category_set(allowed_categories)
        filtered_sim = np.full_like(similarities, -1.0)
        filtered_idx = np.full_like(indices, -1)

        for row in range(len(indices)):
            write_pos = 0
            for col in range(indices.shape[1]):
                db_idx = int(indices[row, col])
                if db_idx < 0 or db_idx >= len(self.metadata):
                    continue
                meta_cat = self.metadata[db_idx].get("top_category", "")
                if _expand_category_set([meta_cat]) & allowed:
                    filtered_sim[row, write_pos] = similarities[row, col]
                    filtered_idx[row, write_pos] = db_idx
                    write_pos += 1
                    if write_pos >= top_k:
                        break

        return filtered_sim, filtered_idx

    def _search_per_category_parallel(
        self,
        query_vectors: np.ndarray,
        top_k: int,
        allowed_categories: list[str],
    ) -> tuple[list[list[float]], list[list[dict]]]:
        n_chunks = len(query_vectors)
        all_scores: list[list[float]] = [[] for _ in range(n_chunks)]
        all_metas:  list[list[dict]]  = [[] for _ in range(n_chunks)]

        def search_one(category: str):
            code = CATEGORY_NAME_TO_CODE.get(category, category)
            safe = code.replace("-", "_").replace(".", "_")
            cat_index = self.cat_indexes.get(code) or self.cat_indexes.get(safe)
            cat_meta  = self.cat_metadata.get(code) or self.cat_metadata.get(safe)
            if cat_index is None or cat_meta is None:
                return []
            sims, idxs = cat_index.search(query_vectors, k=top_k)
            results = []
            for chunk_idx in range(n_chunks):
                for sim, db_idx in zip(sims[chunk_idx], idxs[chunk_idx]):
                    if db_idx >= 0:
                        results.append((chunk_idx, float(sim), cat_meta[db_idx]))
            return results

        with ThreadPoolExecutor(max_workers=min(len(allowed_categories), 4)) as pool:
            futures = {pool.submit(search_one, cat): cat for cat in allowed_categories}
            for future in as_completed(futures):
                for chunk_idx, sim, meta in future.result():
                    all_scores[chunk_idx].append(sim)
                    all_metas[chunk_idx].append(meta)

        return all_scores, all_metas

    # ------------------------------------------------------------------
    # Match building
    # ------------------------------------------------------------------

    def _build_match(
        self,
        chunk_idx: int,
        query_text: str,
        meta: dict,
        db_text: str,
        similarity: float,
        detection: str = "exact",
    ) -> ChunkMatch:
        return ChunkMatch(
            query_chunk_idx=chunk_idx,
            query_text=query_text,
            db_chunk_idx=int(meta.get("chunk_id", -1)),
            db_text=db_text,
            cosine_similarity=round(similarity, 4),
            match_percentage=round(similarity * 100, 2),
            exact_copied_phrases=self._find_exact_phrases(query_text, db_text),
            db_source_type=meta.get("source_type", "unknown"),
            severity=_severity(similarity),
            detection=detection,
        )

    def _find_exact_phrases(
        self, query_text: str, db_text: str, min_words: int = 4
    ) -> list[str]:
        query_words = query_text.split()
        db_words    = db_text.split()
        matcher = difflib.SequenceMatcher(None, query_words, db_words, autojunk=False)

        phrases = set()
        for block in matcher.get_matching_blocks():
            if block.size < min_words:
                continue
            phrase = " ".join(query_words[block.a : block.a + block.size])
            if len(phrase) >= MIN_EXACT_PHRASE_CHARS:
                phrases.add(phrase)
        return list(phrases)

    def _resolve_db_text(self, meta: dict) -> str:
        if text := meta.get("text", ""):
            return text
        lookup_key = (str(meta.get("arxiv_id", "")), int(meta.get("chunk_id", -1)))
        return self._text_lookup.get(lookup_key, "Text not available.")

    # ------------------------------------------------------------------
    # Source ranking
    # ------------------------------------------------------------------

    def _rank_and_trim_sources(
        self, sources: dict[str, SourceResult]
    ) -> list[SourceResult]:
        for source in sources.values():
            source.matches = sorted(
                source.matches,
                key=lambda m: m.cosine_similarity,
                reverse=True,
            )[:self.max_matches_per_source]

        # Sort ALL sources by average similarity (exact copies first, then by score).
        # Previously this dropped paraphrase-only sources when exact copies existed — fixed.
        ranked = sorted(
            sources.values(),
            key=lambda s: (s.has_exact_copies, s.average_similarity if hasattr(s, 'average_similarity') else len(s.matches)),
            reverse=True,
        )
        return ranked[:self.max_sources]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _expand_category_set(categories: list[str]) -> set[str]:
    expanded = set()
    for cat in categories:
        cat = str(cat)
        expanded.add(cat)
        expanded.add(CATEGORY_NAME_TO_CODE.get(cat, cat))
        expanded.add(CATEGORY_CODE_TO_NAME.get(cat, cat))
    return expanded


def _spread_sample(n: int, k: int) -> list[int]:
    if n <= k:
        return list(range(n))
    step = n / k
    return [int(i * step) for i in range(k)]


def _truncate_chunks(chunks: list[str], max_words: int) -> list[str]:
    result, total = [], 0
    for chunk in chunks:
        words = len(chunk.split())
        if total + words > max_words:
            LOGGER.warning(
                "Document truncated at %d words (limit=%d). %d chunks dropped.",
                total, max_words, len(chunks) - len(result),
            )
            break
        result.append(chunk)
        total += words
    return result


def _filter_chunks(chunks: list[str]) -> list[str]:
    """
    Remove chunks that are mostly non-linguistic content:
    - Binary / matrix rows  (e.g. "0 0 1 0 0 1 1 0 ...")
    - Very short chunks (fewer than 8 words)
    - Chunks where > 55% of tokens are purely numeric / single binary digits
    - Chunks with very low unique-word ratio (repetitive symbol noise)
    """
    filtered = []
    for chunk in chunks:
        words = chunk.split()
        if len(words) < 8:
            continue

        # Count purely numeric tokens (integers, floats, single 0/1 digits)
        numeric = sum(
            1 for w in words
            if w in ("0", "1") or w.replace(".", "").replace("-", "").isdigit()
        )
        if numeric / len(words) > 0.55:
            continue

        # Catch matrix rows: lots of single-char tokens that are digits/symbols
        single_char = sum(1 for w in words if len(w) == 1)
        if single_char / len(words) > 0.70:
            continue

        # Catch very low linguistic diversity (e.g. repeated symbol sequences)
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.15 and len(words) > 20:
            continue

        filtered.append(chunk)

    kept  = len(filtered)
    total = len(chunks)
    if kept < total:
        LOGGER.info(
            "Chunk filter: kept %d / %d chunks (removed %d noisy chunks)",
            kept, total, total - kept,
        )
    return filtered


def _format_flagged_chunks(flagged_map: dict[int, dict]) -> list[dict]:
    return [{"chunk_idx": idx, **info} for idx, info in sorted(flagged_map.items())]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Antiplagiarism Engine CLI")

    parser.add_argument("--input",    type=Path, required=True)
    parser.add_argument("--output",   type=Path, default=None)
    parser.add_argument("--arxiv-id", type=str,  default=None)
    parser.add_argument("--pretty",   action="store_true")

    parser.add_argument("--model-name", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--device",     type=str, default="auto",
                        choices=["auto", "cpu", "cuda"])

    parser.add_argument("--artifacts-dir", type=Path,
                        default=Path("backend/core/antiplagiator/artifacts"))
    parser.add_argument("--data-dir", type=Path,
                        default=Path("backend/core/antiplagiator/data/processed"))

    parser.add_argument("--threshold",   type=float, default=0.85)
    parser.add_argument("--top-k",       type=int,   default=5)
    parser.add_argument("--nprobe",      type=int,   default=DEFAULT_NPROBE)
    parser.add_argument("--max-sources", type=int,   default=10)
    parser.add_argument("--max-matches", type=int,   default=5)

    parser.add_argument("--no-routing",           action="store_true")
    parser.add_argument("--per-category-indexes", action="store_true")
    parser.add_argument("--paraphrase-mode",      action="store_true")
    parser.add_argument("--reranker-model", type=str, default=DEFAULT_RERANKER_MODEL)

    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
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
        use_reranker=args.paraphrase_mode,
        reranker_model=args.reranker_model,
    )

    if not engine.is_ready:
        LOGGER.error("Cannot run analysis: %s", engine.init_error)
        sys.exit(1)

    result = engine.analyze_document(
        args.input,
        threshold=args.threshold,
        top_k=args.top_k,
        arxiv_id=args.arxiv_id,
        paraphrase_mode=args.paraphrase_mode,
    )

    indent = 2 if args.pretty else None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=indent, ensure_ascii=False)
        LOGGER.info("Report saved to %s", args.output.absolute())
    else:
        print(json.dumps(result, indent=indent, ensure_ascii=False))

