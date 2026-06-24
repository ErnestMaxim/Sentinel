from __future__ import annotations
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sklearn.neural_network import MLPClassifier

LOGGER = logging.getLogger("category_router")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

THRESHOLD_PENALTY_FACTOR: float = 0.20
THRESHOLD_FLOOR: float          = 0.55
CROSS_DOMAIN_ALERT_RATIO: float = 0.35
CROSS_DOMAIN_MIN_MATCHES: int   = 3


# ---------------------------------------------------------------------------
# Core confidence helper (shared by all options)
# ---------------------------------------------------------------------------

def classifier_confidence(clf: "MLPClassifier", embedding: np.ndarray) -> float:
    """
    Entropy-based confidence in [0, 1].
    1.0 = completely certain (all probability mass on one class).
    0.0 = maximally uncertain (uniform distribution).
    """
    probs       = clf.predict_proba([embedding])[0]
    probs       = np.clip(probs, 1e-12, 1.0)
    entropy     = -np.sum(probs * np.log(probs))
    max_entropy = np.log(len(probs))
    return float(1.0 - entropy / max_entropy)


def get_candidate_categories(
    clf: "MLPClassifier",
    embedding: np.ndarray,
    top_k: int = 3,
    min_prob: float = 0.05,
) -> list[str]:
    """
    Return up to `top_k` category names that each have >= `min_prob`.
    Always guarantees at least 1 result (the argmax), even if below min_prob.
    """
    probs   = clf.predict_proba([embedding])[0]
    classes = clf.classes_
    ranked  = sorted(zip(classes, probs), key=lambda x: x[1], reverse=True)

    results: list[str] = [ranked[0][0]]
    for cat, prob in ranked[1:top_k]:
        if prob >= min_prob:
            results.append(cat)
    return results


# ---------------------------------------------------------------------------
# Original document-level routing (kept for backwards compatibility)
# ---------------------------------------------------------------------------

def route(
    clf: "MLPClassifier",
    embedding: np.ndarray,
    confidence_threshold: float = 0.40,
    top_k: int = 2,
    min_prob: float = 0.05,
) -> tuple[list[str] | None, float]:
    """
    Decide which categories to search for a single embedding.

    Returns
    -------
    (categories, confidence)
      categories : list of category strings, or None -> fall back to global
      confidence : float in [0, 1]
    """
    conf = classifier_confidence(clf, embedding)
    if conf < confidence_threshold:
        LOGGER.debug("Low confidence (%.3f < %.3f) — global search", conf, confidence_threshold)
        return None, conf

    categories = get_candidate_categories(clf, embedding, top_k=top_k, min_prob=min_prob)
    LOGGER.debug("Routing to %s (conf=%.3f)", categories, conf)
    return categories, conf


# ---------------------------------------------------------------------------
# OPTION 1 — Chunk-level routing
# ---------------------------------------------------------------------------

def route_per_chunk(
    clf: "MLPClassifier",
    query_vectors: np.ndarray,
    confidence_threshold: float = 0.35,
    top_k: int = 2,
    min_prob: float = 0.05,
) -> dict[int, list[str] | None]:
    """
    OPTION 1 — Classify each chunk independently.

    Instead of voting across a sample of chunks to pick one category for the
    whole document, each chunk gets its own routing decision. A math-heavy chunk
    in a CS paper routes to `math`; a CS-heavy chunk stays in `cs`. Directly
    solves the cross-discipline recall problem.

    Parameters
    ----------
    clf                  : trained MLPClassifier
    query_vectors        : all chunk embeddings for the document (n_chunks x dim)
    confidence_threshold : minimum entropy-confidence to use per-category routing
                           (below this -> chunk uses global search)
    top_k                : max categories per chunk
    min_prob             : minimum class probability to include as a candidate

    Returns
    -------
    dict mapping chunk_idx -> list[str] categories (or None for global fallback)
    """
    n_chunks    = len(query_vectors)
    result:     dict[int, list[str] | None] = {}

    # Batch predict_proba for efficiency — one call for all chunks
    all_probs   = clf.predict_proba(query_vectors)
    all_classes = clf.classes_

    for i in range(n_chunks):
        probs   = all_probs[i]
        clipped = np.clip(probs, 1e-12, 1.0)
        entropy = -np.sum(clipped * np.log(clipped))
        max_ent = np.log(len(probs))
        conf    = float(1.0 - entropy / max_ent)

        if conf < confidence_threshold:
            result[i] = None
            LOGGER.debug("Chunk %d -> global (conf=%.3f)", i, conf)
            continue

        ranked = sorted(zip(all_classes, probs), key=lambda x: x[1], reverse=True)
        cats   = [ranked[0][0]]
        for cat, prob in ranked[1:top_k]:
            if prob >= min_prob:
                cats.append(cat)

        result[i] = cats
        LOGGER.debug("Chunk %d -> %s (conf=%.3f)", i, cats, conf)

    global_chunks = sum(1 for v in result.values() if v is None)
    LOGGER.info(
        "route_per_chunk: %d chunks, %d per-category, %d global fallback",
        n_chunks, n_chunks - global_chunks, global_chunks,
    )
    return result


# ---------------------------------------------------------------------------
# OPTION 2 — Confidence-aware retrieval threshold
# ---------------------------------------------------------------------------

def confidence_aware_threshold(
    clf: "MLPClassifier",
    query_vectors: np.ndarray,
    base_threshold: float,
    penalty_factor: float = THRESHOLD_PENALTY_FACTOR,
    floor: float = THRESHOLD_FLOOR,
    sample_size: int = 8,
) -> tuple[float, float]:
    """
    OPTION 2 — Compute an effective FAISS retrieval threshold that adapts
    based on the classifier's confidence in the document's category.

    High confidence (focused paper)    -> use base_threshold (strict)
    Low confidence (interdisciplinary) -> lower threshold (wider net)

    Formula:
        effective = max(floor, base - (1 - avg_confidence) * penalty_factor)

    Parameters
    ----------
    clf             : trained MLPClassifier
    query_vectors   : all chunk embeddings (n_chunks x dim)
    base_threshold  : the user-configured threshold (e.g. 0.75)
    penalty_factor  : max reduction applied when confidence=0.0 (default 0.20)
    floor           : minimum possible effective threshold (default 0.55)
    sample_size     : number of chunks to sample for confidence estimation

    Returns
    -------
    (effective_threshold, avg_confidence)
    """
    n = len(query_vectors)
    if n == 0:
        return base_threshold, 0.0

    step    = max(1, n // sample_size)
    indices = list(range(0, n, step))[:sample_size]
    sample  = query_vectors[indices]

    all_probs   = clf.predict_proba(sample)
    confidences = []
    for probs in all_probs:
        clipped = np.clip(probs, 1e-12, 1.0)
        entropy = -np.sum(clipped * np.log(clipped))
        max_ent = np.log(len(probs))
        confidences.append(1.0 - entropy / max_ent)

    avg_confidence = float(np.mean(confidences))
    penalty        = (1.0 - avg_confidence) * penalty_factor
    effective      = max(floor, base_threshold - penalty)

    LOGGER.info(
        "confidence_aware_threshold: base=%.3f avg_conf=%.3f penalty=%.3f effective=%.3f",
        base_threshold, avg_confidence, penalty, effective,
    )
    return effective, avg_confidence


# ---------------------------------------------------------------------------
# OPTION 3 — Cross-domain alert
# ---------------------------------------------------------------------------

def detect_cross_domain(
    clf: "MLPClassifier",
    query_vectors: np.ndarray,
    matched_sources: list[dict],
    alert_ratio: float = CROSS_DOMAIN_ALERT_RATIO,
    min_matches: int = CROSS_DOMAIN_MIN_MATCHES,
    sample_size: int = 8,
) -> dict | None:
    """
    OPTION 3 — Detect when a document borrows heavily from a different field.

    Compares:
      - The predicted top category of the query document (from classifier)
      - The `top_category` fields of all matched source papers

    If >= `alert_ratio` of match weight comes from a category other than the
    document's predicted category, emit a cross_domain_alert dict.

    Parameters
    ----------
    clf             : trained MLPClassifier
    query_vectors   : all chunk embeddings for the query document
    matched_sources : list of source dicts from engine, each with:
                        - top_category (str)
                        - match_count  (int)
                        - average_similarity_percent (float)
    alert_ratio     : fraction of weighted matches from foreign category to alert
    min_matches     : skip alert if total match count is below this
    sample_size     : chunks to sample for query category estimation

    Returns
    -------
    dict with alert details, or None if no cross-domain signal detected.

    The returned dict is included in the engine report JSON as:
        result["cross_domain_alert"]

    Example output:
    {
        "detected": True,
        "query_predicted_category": "Computer Science",
        "query_confidence": 0.82,
        "dominant_source_category": "Mathematics",
        "foreign_match_ratio": 0.61,
        "foreign_weighted_score": 45.3,
        "total_matches": 18,
        "category_breakdown": { ... },
        "interpretation": "..."
    }
    """
    if not matched_sources:
        return None

    total_matches = sum(s.get("match_count", 0) for s in matched_sources)
    if total_matches < min_matches:
        LOGGER.debug("cross_domain: too few matches (%d < %d) — skipping", total_matches, min_matches)
        return None

    # ── Predict query category from a sample of chunk vectors ────────────
    n       = len(query_vectors)
    step    = max(1, n // sample_size)
    indices = list(range(0, n, step))[:sample_size]
    sample  = query_vectors[indices]

    all_probs      = clf.predict_proba(sample)
    mean_probs     = all_probs.mean(axis=0)
    query_category = clf.classes_[int(np.argmax(mean_probs))]

    clipped    = np.clip(mean_probs, 1e-12, 1.0)
    entropy    = -np.sum(clipped * np.log(clipped))
    max_ent    = np.log(len(mean_probs))
    query_conf = float(1.0 - entropy / max_ent)

    # ── Tally weighted matches by source category ─────────────────────────
    # weight = match_count * average_similarity — stronger matches count more
    category_weight: dict[str, float] = defaultdict(float)
    category_count:  dict[str, int]   = defaultdict(int)

    for source in matched_sources:
        src_cat = str(source.get("top_category", "")).strip()
        if not src_cat or src_cat == "unknown":
            continue
        n_matches = int(source.get("match_count", 0))
        avg_sim   = float(source.get("average_similarity_percent", 0.0))
        category_weight[src_cat] += n_matches * avg_sim
        category_count[src_cat]  += n_matches

    if not category_weight:
        return None

    total_weight = sum(category_weight.values())
    if total_weight == 0:
        return None

    dominant_src_cat = max(category_weight, key=category_weight.__getitem__)
    dominant_weight  = category_weight[dominant_src_cat]
    foreign_ratio    = dominant_weight / total_weight

    # Normalise for comparison — strip hyphens/underscores/spaces/case
    def _norm(s: str) -> str:
        return s.lower().replace("-", "").replace("_", "").replace(" ", "")

    if _norm(dominant_src_cat) == _norm(query_category) or foreign_ratio < alert_ratio:
        LOGGER.debug(
            "cross_domain: dominant=%s (%.0f%%) matches query=%s — no alert",
            dominant_src_cat, foreign_ratio * 100, query_category,
        )
        return None

    interpretation = (
        f"This document is classified as '{query_category}' "
        f"(confidence {query_conf:.0%}) but {foreign_ratio:.0%} of its "
        f"similarity matches come from '{dominant_src_cat}'. "
        f"This may indicate cross-domain idea borrowing or insufficient citation."
    )

    alert = {
        "detected":                 True,
        "query_predicted_category": query_category,
        "query_confidence":         round(query_conf, 3),
        "dominant_source_category": dominant_src_cat,
        "foreign_match_ratio":      round(foreign_ratio, 3),
        "foreign_weighted_score":   round(dominant_weight, 2),
        "total_matches":            total_matches,
        "category_breakdown": {
            cat: {
                "match_count":    category_count[cat],
                "weighted_score": round(w, 2),
                "weight_ratio":   round(w / total_weight, 3),
            }
            for cat, w in sorted(category_weight.items(), key=lambda x: -x[1])
        },
        "interpretation": interpretation,
    }

    LOGGER.info(
        "CROSS-DOMAIN ALERT: query=%s -> dominant_source=%s (%.0f%% of matches)",
        query_category, dominant_src_cat, foreign_ratio * 100,
    )
    return alert