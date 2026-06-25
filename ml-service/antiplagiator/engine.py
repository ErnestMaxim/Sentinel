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

from category_router import (
    route,
    route_per_chunk,
    confidence_aware_threshold,
    detect_cross_domain,
)
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

MAX_WORDS                        = 100_000 
ROUTING_SAMPLE_SIZE              = 8
HIGH_CONFIDENCE_THRESHOLD        = 0.90
MIN_EXACT_PHRASE_CHARS           = 50
PARAPHRASE_RETRIEVAL_THRESHOLD   = 0.78
PARAPHRASE_CROSS_SCORE_THRESHOLD = 3.5
DEFAULT_RERANKER_MODEL           = "cross-encoder/ms-marco-MiniLM-L-6-v2"


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
    query_chunk_idx:      int
    query_text:           str
    db_chunk_idx:         int
    db_text:              str
    cosine_similarity:    float
    match_percentage:     float
    exact_copied_phrases: list[str]
    db_source_type:       str
    severity:             str
    detection:            str = "exact"

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
    arxiv_id:       str
    title:          str
    matches:        list[ChunkMatch] = field(default_factory=list)
    top_category:   str = ""
    # Each source tracks its own coverage set without being deducted by positions
    # already claimed by another source, eliminating processing-order bias.
    _own_positions: set = field(default_factory=set, repr=False)

    @property
    def flagged_word_count(self) -> int:
        return len(self._own_positions)

    @property
    def has_exact_copies(self) -> bool:
        return any(m.severity == "identical" for m in self.matches)

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
            "top_category":               self.top_category,
            "match_count":                len(self.matches),
            "average_similarity_percent": round(self.average_similarity, 2),
            "has_exact_copies":           self.has_exact_copies,
            "score_contribution_percent": contribution,
            "matches":                    [m.to_dict() for m in self.matches],
        }


@dataclass
class RoutingDecision:
    enabled:    bool
    categories: list[str] | None
    confidence: float
    strategy:   str

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled":    self.enabled,
            "categories": self.categories,
            "confidence": round(self.confidence, 3),
            "strategy":   self.strategy,
        }


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
        classifier_artifact: str = "category_classifier_v2.pkl",
        confidence_threshold: float = 0.40,
        routing_top_k: int = 2,
        use_per_category_indexes: bool = False,
        use_reranker: bool = False,
        reranker_model: str = DEFAULT_RERANKER_MODEL,
    ) -> None:
        self.max_sources              = max_sources
        self.max_matches_per_source   = max_matches_per_source
        self.nprobe                   = nprobe
        self.use_category_routing     = use_category_routing
        self.confidence_threshold     = confidence_threshold
        self.routing_top_k            = routing_top_k
        self.use_per_category_indexes = use_per_category_indexes

        self.is_ready   = False
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

    def _setup_modules(self, model_name: str, device: str) -> None:
        self._session   = build_session()
        self._extractor = TextExtractor(self._session)
        LOGGER.info("Loading SentenceTransformer: %s", model_name)
        self._model = SentenceTransformer(model_name, device=device)

    def _setup_indexes(self, artifacts_dir: Path, data_dir: Path, nprobe: int) -> None:
        remote_url = os.getenv("FAISS_REMOTE_URL", "").strip()

        if remote_url:
            LOGGER.info("FAISS_REMOTE_URL detected — using Modal RemoteIndex")
            from engine_modules.remote_index import RemoteIndex
            remote             = RemoteIndex.from_env()
            self.index         = remote
            self.metadata      = remote.metadata
            self.dataset_texts = []
            self._text_lookup  = {}
            self.cat_indexes   = {}
            self.cat_metadata  = {}
            LOGGER.info("RemoteIndex ready -> %s", remote_url)
        else:
            LOGGER.info("No FAISS_REMOTE_URL — using local FAISS index")
            self.index, self.metadata = load_global_index(artifacts_dir, nprobe)

            dataset_path       = data_dir / "chunked_database.jsonl"
            self.dataset_texts = load_dataset_texts(dataset_path)
            self._text_lookup  = build_text_lookup(self.dataset_texts, self.metadata)

            self.cat_indexes:  dict[str, faiss.Index] = {}
            self.cat_metadata: dict[str, list[dict]]  = {}
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
            from antiplagiator.engine_modules.classifier import register_classifier_classes
            register_classifier_classes()
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

        t0 = time.monotonic()
        chunks, full_text, display_text = self._extractor.read_and_chunk(
            file_path, arxiv_id=arxiv_id
        )
        if not chunks:
            return {
                "file_name":                       file_path.name,
                "global_plagiarism_score_percent": 0.0,
                "total_reported_sources":          0,
                "document_stats":                  {"total_words": 0, "total_chunks_analyzed": 0},
                "sources":                         [],
                "error":                           "No valid text could be extracted.",
            }

        chunks      = _truncate_chunks(chunks, MAX_WORDS)
        chunks      = _filter_chunks(chunks)
        total_words = sum(len(c.split()) for c in chunks)
        timings["extraction_s"] = round(time.monotonic() - t0, 3)

        t1            = time.monotonic()
        query_vectors = self._encode_batch(chunks)
        timings["encoding_s"] = round(time.monotonic() - t1, 3)

        # Option 2 — Confidence-aware threshold: interdisciplinary documents get
        # a slightly lower threshold so the engine casts a wider net.
        if self.use_category_routing and self.clf is not None and not active_paraphrase:
            effective_threshold, avg_conf = confidence_aware_threshold(
                self.clf,
                query_vectors,
                base_threshold=threshold,
            )
            LOGGER.info(
                "Option 2 — confidence_aware_threshold: "
                "base=%.3f → effective=%.3f (avg_conf=%.3f)",
                threshold, effective_threshold, avg_conf,
            )
        else:
            effective_threshold = (
                PARAPHRASE_RETRIEVAL_THRESHOLD if active_paraphrase else threshold
            )
            avg_conf = 0.0

        routing = self._decide_routing(query_vectors)

        # Option 1 — Per-chunk routing: each chunk gets its own category so a
        # math-heavy chunk in a CS paper routes to `math` rather than `cs`.
        is_remote = hasattr(self.index, "search_category")
        can_do_per_chunk = (
            self.use_category_routing
            and self.clf is not None
            and self.use_per_category_indexes
            and (bool(self.cat_indexes) or is_remote)
        )

        if can_do_per_chunk:
            chunk_routes = route_per_chunk(
                self.clf,
                query_vectors,
                confidence_threshold=0.35,
                top_k=self.routing_top_k,
            )
            LOGGER.info(
                "Option 1 — route_per_chunk: %d/%d chunks routed to categories",
                sum(1 for v in chunk_routes.values() if v is not None),
                len(chunks),
            )
        else:
            chunk_routes = {i: routing.categories for i in range(len(chunks))}

        t2 = time.monotonic()
        sources, flagged_chunk_map, counted_word_positions = self._run_search(
            chunks, query_vectors,
            retrieval_threshold=effective_threshold,
            flag_threshold=threshold,
            top_k=top_k,
            routing=routing,
            chunk_routes=chunk_routes,
            self_arxiv_id=arxiv_id,
            paraphrase_mode=active_paraphrase,
        )
        timings["search_s"] = round(time.monotonic() - t2, 3)

        t3 = time.monotonic()
        ranked_sources = self._rank_and_trim_sources(sources)

        flagged_words         = len(counted_word_positions)
        word_coverage         = flagged_words / total_words if total_words > 0 else 0.0
        actual_document_words = len(full_text.split()) if full_text else 0

        timings["ranking_s"] = round(time.monotonic() - t3, 3)
        timings["total_s"]   = round(sum(timings.values()), 3)

        # Option 3 — Cross-domain alert: flags when a significant fraction of
        # matches come from a different field than the query document.
        cross_domain_alert: dict[str, Any] = {"detected": False}
        if self.use_category_routing and self.clf is not None and ranked_sources:
            sources_for_alert = [
                {
                    "top_category":               s.top_category,
                    "match_count":                len(s.matches),
                    "average_similarity_percent": s.average_similarity,
                }
                for s in ranked_sources
            ]
            alert = detect_cross_domain(
                self.clf,
                query_vectors,
                sources_for_alert,
            )
            if alert:
                cross_domain_alert = alert
                LOGGER.info(
                    "Option 3 — cross-domain alert: query=%s dominant_source=%s (%.0f%%)",
                    alert["query_predicted_category"],
                    alert["dominant_source_category"],
                    alert["foreign_match_ratio"] * 100,
                )

        return {
            "file_name":                       file_path.name,
            "global_plagiarism_score_percent": round(word_coverage * 100, 2),
            "total_reported_sources":          len(ranked_sources),
            "total_suspicious_sources":        len(sources),
            "full_text":                       full_text,
            "display_text":                    display_text,
            "document_stats": {
                "total_words":           actual_document_words,
                "flagged_words":         flagged_words,
                "total_chunks_analyzed": len(chunks),
            },
            "flagged_chunks":     _format_flagged_chunks(flagged_chunk_map),
            "sources":            [s.to_dict(total_words) for s in ranked_sources],
            "cross_domain_alert": cross_domain_alert,
            "analysis_config": {
                "routing":               routing.to_dict(),
                "threshold_used":        threshold,
                "effective_threshold":   round(effective_threshold, 3),
                "avg_classifier_conf":   round(avg_conf, 3),
                "top_k":                 top_k,
                "paraphrase_mode":       active_paraphrase,
                "embedding_model":       DEFAULT_MODEL,
                "per_chunk_routing":     can_do_per_chunk,
                "timing":                timings,
            },
        }

    def _encode_batch(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        ).astype("float32")

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

        is_remote = hasattr(self.index, "search_category")
        strategy  = (
            "per_category"
            if self.use_per_category_indexes and (self.cat_indexes or is_remote)
            else "post_filter"
        )
        return RoutingDecision(
            enabled=True, categories=top_categories,
            confidence=avg_confidence, strategy=strategy,
        )

    def _prebatch_remote_category_searches(
        self,
        chunks: list[str],
        chunk_routes: dict[int, list[str] | None],
        top_k: int,
    ) -> dict[tuple[int, str], tuple[list[float], list[dict]]]:
        """
        Group all chunks by assigned category and fire one parallel request per
        category, reducing Modal calls from O(N_chunks × N_categories) to
        O(N_categories).

        Returns dict mapping (chunk_idx, category_safe) -> (scores, metas).
        """
        cat_to_chunks: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for chunk_idx, chunk_text in enumerate(chunks):
            cats = chunk_routes.get(chunk_idx)
            if cats is None:
                continue
            for cat in cats:
                code = CATEGORY_NAME_TO_CODE.get(cat, cat)
                safe = code.replace("-", "_").replace(".", "_")
                cat_to_chunks[safe].append((chunk_idx, chunk_text))

        if not cat_to_chunks:
            return {}

        total_assignments = sum(len(v) for v in cat_to_chunks.values())
        LOGGER.info(
            "Pre-batching %d category searches (%d total chunk-category assignments — "
            "was %d sequential calls)",
            len(cat_to_chunks), total_assignments, total_assignments,
        )

        results: dict[tuple[int, str], tuple[list[float], list[dict]]] = {}

        def _fetch(cat_safe: str, pairs: list[tuple[int, str]]):
            texts = [text for _, text in pairs]
            idxs  = [idx  for idx,  _ in pairs]
            scores_list, metas_list = self.index.search_category(
                texts, cat_safe, k=top_k, threshold=0.0,
            )
            return cat_safe, idxs, scores_list, metas_list

        max_workers = min(len(cat_to_chunks), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_fetch, cat_safe, pairs): cat_safe
                for cat_safe, pairs in cat_to_chunks.items()
            }
            for future in as_completed(futures):
                cat_safe = futures[future]
                try:
                    cat_safe, idxs, scores_list, metas_list = future.result()
                    for local_i, orig_idx in enumerate(idxs):
                        results[(orig_idx, cat_safe)] = (
                            scores_list[local_i],
                            metas_list[local_i],
                        )
                except Exception as exc:
                    LOGGER.error(
                        "Batch category search failed (%s): %s", cat_safe, exc
                    )

        LOGGER.info(
            "Pre-batch complete — %d (chunk, category) results cached",
            len(results),
        )
        return results

    def _run_search(
        self,
        chunks: list[str],
        query_vectors: np.ndarray,
        retrieval_threshold: float,
        flag_threshold: float,
        top_k: int,
        routing: RoutingDecision,
        chunk_routes: dict[int, list[str] | None],
        self_arxiv_id: str | None,
        paraphrase_mode: bool,
    ) -> tuple[dict[str, SourceResult], dict[int, dict], set[int]]:
        sources:                dict[str, SourceResult] = {}
        flagged_chunk_map:      dict[int, dict]         = {}
        counted_word_positions: set[int]                = set()

        word_offset       = 0
        chunk_word_counts = [len(c.split()) for c in chunks]
        is_remote         = hasattr(self.index, "search_category")

        if not is_remote and hasattr(self.index, "set_query_texts"):
            self.index.set_query_texts(chunks)

        remote_cat_cache: dict[tuple[int, str], tuple[list[float], list[dict]]] = {}
        if is_remote and self.use_per_category_indexes:
            remote_cat_cache = self._prebatch_remote_category_searches(
                chunks, chunk_routes, top_k,
            )

        for chunk_idx, chunk_text in enumerate(chunks):
            chunk_words = chunk_word_counts[chunk_idx]
            chunk_vec   = query_vectors[chunk_idx:chunk_idx + 1]
            categories  = chunk_routes.get(chunk_idx)

            use_per_cat_remote = (
                is_remote
                and categories is not None
                and self.use_per_category_indexes
            )
            use_per_cat_local = (
                not is_remote
                and categories is not None
                and bool(self.cat_indexes)
                and self.use_per_category_indexes
            )

            if use_per_cat_remote:
                for cat in categories:
                    code   = CATEGORY_NAME_TO_CODE.get(cat, cat)
                    safe   = code.replace("-", "_").replace(".", "_")
                    scores, metas = remote_cat_cache.get((chunk_idx, safe), ([], []))
                    if scores:
                        flagged_info = self._process_per_category_hits(
                            chunk_idx, chunk_text, scores, metas,
                            retrieval_threshold, flag_threshold,
                            word_offset, chunk_words,
                            sources, counted_word_positions, self_arxiv_id,
                            paraphrase_mode,
                        )
                        if flagged_info:
                            flagged_chunk_map[chunk_idx] = flagged_info

            elif use_per_cat_local:
                score_rows, meta_rows = self._search_per_category_parallel(
                    chunk_vec, top_k, categories,
                )
                scores = score_rows[0]
                metas  = meta_rows[0]
                flagged_info = self._process_per_category_hits(
                    chunk_idx, chunk_text, scores, metas,
                    retrieval_threshold, flag_threshold,
                    word_offset, chunk_words,
                    sources, counted_word_positions, self_arxiv_id,
                    paraphrase_mode,
                )
                if flagged_info:
                    flagged_chunk_map[chunk_idx] = flagged_info

            else:
                if is_remote:
                    self.index.set_query_texts([chunk_text])

                similarities, db_indices = self._search_global(
                    chunk_vec, top_k, routing.categories,
                )
                flagged_info = self._process_global_hits(
                    chunk_idx, chunk_text,
                    similarities[0], db_indices[0],
                    retrieval_threshold, flag_threshold, top_k,
                    word_offset, chunk_words,
                    sources, counted_word_positions, self_arxiv_id,
                    paraphrase_mode,
                )
                if flagged_info:
                    flagged_chunk_map[chunk_idx] = flagged_info

            word_offset += chunk_words

        for src in sources.values():
            if not src.top_category and src.matches:
                for meta in self.metadata:
                    if meta.get("arxiv_id") == src.arxiv_id:
                        src.top_category = str(meta.get("top_category", ""))
                        break

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
        return self._apply_flag_threshold(
            chunk_idx, chunk_text, candidates, flag_threshold,
            word_offset, chunk_words, sources, counted_positions,
        )

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
        best_similarity  = 0.0
        best_match_info: dict | None = None
        matching_source_ids: list[str] = []

        for similarity, meta, db_text in candidates:
            if similarity < flag_threshold:
                continue

            # Guard against formula-structural false positives: two unrelated
            # math-heavy papers can score above threshold by sharing normalised
            # formula tokens (SUM, PARTIAL, Greek letters) without sharing content.
            # Bypass for similarity >= 0.90 — at that level false positives between
            # different papers don't occur; the bypass prevents real plagiarism from
            # being filtered when re-extraction alters formula rendering.
            if similarity < 0.90:
                overlap = _content_word_overlap(chunk_text, db_text)
                if overlap < _MIN_CONTENT_WORD_OVERLAP:
                    LOGGER.debug(
                        "Skipping hit (sim=%.4f arxiv=%s) — content word overlap "
                        "too low (%d < %d); likely formula-structural false positive",
                        similarity, meta.get("arxiv_id", "?"),
                        overlap, _MIN_CONTENT_WORD_OVERLAP,
                    )
                    continue

            arxiv_id = meta.get("arxiv_id", "N/A")
            match    = self._build_match(
                chunk_idx, chunk_text, meta, db_text, similarity, detection="exact",
            )
            source = sources.setdefault(
                arxiv_id,
                SourceResult(
                    arxiv_id,
                    meta.get("title", "N/A"),
                    top_category=meta.get("top_category", ""),
                ),
            )
            if not source.top_category:
                source.top_category = meta.get("top_category", "")
            source.matches.append(match)

            if arxiv_id not in matching_source_ids:
                matching_source_ids.append(arxiv_id)

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
                matching_source_ids, sources,
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
        matching_source_ids: list[str] = []

        for result in rerank_results:
            if not result.is_paraphrase:
                continue
            meta       = meta_by_text.get(result.candidate_text)
            if meta is None:
                continue
            normalised = _normalize_cross_score(result.cross_score)
            arxiv_id   = meta.get("arxiv_id", "N/A")
            match      = self._build_match(
                chunk_idx, chunk_text, meta, result.candidate_text,
                normalised, detection="paraphrase",
            )
            source = sources.setdefault(
                arxiv_id,
                SourceResult(
                    arxiv_id,
                    meta.get("title", "N/A"),
                    top_category=meta.get("top_category", ""),
                ),
            )
            if not source.top_category:
                source.top_category = meta.get("top_category", "")
            source.matches.append(match)

            if arxiv_id not in matching_source_ids:
                matching_source_ids.append(arxiv_id)

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
                matching_source_ids, sources,
            )
            return best_match_info
        return None

    def _account_flagged_words(
        self,
        word_offset: int,
        chunk_words: int,
        counted_positions: set[int],
        matching_source_ids: list[str],
        sources: dict[str, SourceResult],
    ) -> None:
        """
        Update word-slot coverage for the global dedup set and for every source
        that matched this chunk.

        ``counted_positions`` is the union of all flagged positions and is used
        exclusively to compute the overall plagiarism score.

        Each source in ``matching_source_ids`` gets its own independent position
        set so that processing order doesn't determine which source receives credit
        for a shared chunk — previously the first-matched source claimed all new
        positions while later sources got zero.
        """
        chunk_positions = set(range(word_offset, word_offset + chunk_words))
        counted_positions.update(chunk_positions)
        for src_id in matching_source_ids:
            if src_id in sources:
                sources[src_id]._own_positions.update(chunk_positions)

    def _search_global(
        self,
        query_vectors: np.ndarray,
        top_k: int,
        categories: list[str] | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        similarities, indices = self.index.search(query_vectors, k=top_k)
        return similarities, indices

    def _filter_by_category(
        self,
        similarities: np.ndarray,
        indices: np.ndarray,
        top_k: int,
        allowed_categories: list[str],
    ) -> tuple[np.ndarray, np.ndarray]:
        allowed      = _expand_category_set(allowed_categories)
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
        n_chunks   = len(query_vectors)
        all_scores: list[list[float]] = [[] for _ in range(n_chunks)]
        all_metas:  list[list[dict]]  = [[] for _ in range(n_chunks)]

        def search_one(category: str):
            code      = CATEGORY_NAME_TO_CODE.get(category, category)
            safe      = code.replace("-", "_").replace(".", "_")
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
        matcher     = difflib.SequenceMatcher(None, query_words, db_words, autojunk=False)
        phrases     = set()
        for block in matcher.get_matching_blocks():
            if block.size < min_words:
                continue
            phrase = " ".join(query_words[block.a: block.a + block.size])
            if len(phrase) >= MIN_EXACT_PHRASE_CHARS:
                phrases.add(phrase)
        return list(phrases)

    def _resolve_db_text(self, meta: dict) -> str:
        if text := meta.get("text", ""):
            return text
        lookup_key = (str(meta.get("arxiv_id", "")), int(meta.get("chunk_id", -1)))
        return self._text_lookup.get(lookup_key, "Text not available.")

    def _rank_and_trim_sources(
        self, sources: dict[str, SourceResult]
    ) -> list[SourceResult]:
        for source in sources.values():
            source.matches = sorted(
                source.matches,
                key=lambda m: m.cosine_similarity,
                reverse=True,
            )[:self.max_matches_per_source]

        ranked = sorted(
            sources.values(),
            key=lambda s: (
                s.has_exact_copies,
                s.average_similarity if hasattr(s, "average_similarity") else len(s.matches),
            ),
            reverse=True,
        )
        return ranked[:self.max_sources]


# ---------------------------------------------------------------------------
# Formula-structural false-positive guard
#
# After normalisation, two unrelated math-heavy papers (e.g. in quant_ph) can
# look similar because they share structural tokens like SUM, PARTIAL, _(j), ^(2).
# We require at least _MIN_CONTENT_WORD_OVERLAP non-formula content words in
# common. Real plagiarism shares domain vocabulary ("stabilizer", "syndrome",
# "codeword"); structural false positives share only formula tokens and
# single-letter variable names.
# ---------------------------------------------------------------------------

_MIN_CONTENT_WORD_OVERLAP = 2

# Greek letters included: every quant_ph paper uses alpha/beta/gamma — they
# provide no discriminative power between papers in the same category.
_FORMULA_STRUCTURE_TOKENS: frozenset[str] = frozenset({
    "sum", "int", "prod", "lim", "sup", "inf",
    "exp", "log", "ln", "sin", "cos", "tan",
    "partial", "nabla", "hbar", "sqrt", "frac",
    "times", "dot", "plusminus", "leq", "geq", "neq", "approx",
    "equiv", "propto", "rightarrow", "leftarrow", "leftrightarrow",
    "implies", "iff", "tensor", "oplus", "dagger", "ddagger",
    "forall", "exists", "subset", "supset", "intersect", "union",
    "in", "notin", "not",
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta",
    "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
    "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
})


def _content_word_overlap(text1: str, text2: str, min_len: int = 5) -> int:
    """
    Count shared content words (length >= min_len) that are not formula
    structure tokens or pure numeric tokens.
    """
    def _extract(text: str) -> set[str]:
        words: set[str] = set()
        for raw in text.lower().split():
            w = raw.strip(".,;:!?()[]{}\"'")
            if len(w) < min_len:
                continue
            if w in _FORMULA_STRUCTURE_TOKENS:
                continue
            if w.startswith("_(") or w.startswith("^("):
                continue
            cleaned = w.replace(".", "").replace("-", "").replace("e", "")
            if cleaned.isdigit():
                continue
            words.add(w)
        return words

    return len(_extract(text1) & _extract(text2))


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
    - Binary / matrix rows (e.g. "0 0 1 0 0 1 1 0 ...")
    - Fewer than 8 words
    - More than 55% purely numeric / single binary digit tokens
    - Very low unique-word ratio (repetitive symbol noise)
    """
    filtered = []
    for chunk in chunks:
        words = chunk.split()
        if len(words) < 8:
            continue

        numeric = sum(
            1 for w in words
            if w in ("0", "1") or w.replace(".", "").replace("-", "").isdigit()
        )
        if numeric / len(words) > 0.55:
            continue

        single_char = sum(1 for w in words if len(w) == 1)
        if single_char / len(words) > 0.70:
            continue

        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.10 and len(words) > 20:
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