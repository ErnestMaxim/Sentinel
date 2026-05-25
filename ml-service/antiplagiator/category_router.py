from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sklearn.neural_network import MLPClassifier

LOGGER = logging.getLogger("category_router")


# ── entropy-based confidence ──────────────────────────────────────────────────

def classifier_confidence(clf: "MLPClassifier", embedding: np.ndarray) -> float:
  
    probs = clf.predict_proba([embedding])[0]
    probs = np.clip(probs, 1e-12, 1.0)
    entropy = -np.sum(probs * np.log(probs))
    max_entropy = np.log(len(probs))
    return float(1.0 - entropy / max_entropy)


# ── top-K beam from predict_proba ─────────────────────────────────────────────

def get_candidate_categories(
    clf: "MLPClassifier",
    embedding: np.ndarray,
    top_k: int = 3,
    min_prob: float = 0.10,
) -> list[str]:
    """
    Return up to `top_k` category names that each have at least `min_prob`
    predicted probability.  Guarantees at least 1 result (the argmax).

    Parameters
    ----------
    clf       : trained MLPClassifier with predict_proba support
    embedding : 1-D float32 array (single document embedding)
    top_k     : maximum number of categories to return
    min_prob  : minimum probability threshold to include a category

    Returns
    -------
    List of category name strings (same vocabulary as clf.classes_)
    """
    probs   = clf.predict_proba([embedding])[0]
    classes = clf.classes_

    ranked = sorted(zip(classes, probs), key=lambda x: x[1], reverse=True)

    # Always include argmax even if it falls below min_prob
    results: list[str] = [ranked[0][0]]
    for cat, prob in ranked[1:top_k]:
        if prob >= min_prob:
            results.append(cat)

    return results


# ── high-level routing decision ───────────────────────────────────────────────

def route(
    clf: "MLPClassifier",
    embedding: np.ndarray,
    confidence_threshold: float = 0.40,
    top_k: int = 2,
    min_prob: float = 0.10,
) -> tuple[list[str] | None, float]:
    """
    Decide which categories to search, or return None to fall back to global.

    Returns
    -------
    (categories, confidence)
      categories : list of category strings to restrict search to,
                   or None if confidence is too low (→ search globally)
      confidence : float in [0, 1]
    """
    conf = classifier_confidence(clf, embedding)

    if conf < confidence_threshold:
        LOGGER.debug(
            "Low classifier confidence (%.3f < %.3f) — falling back to global search",
            conf, confidence_threshold,
        )
        return None, conf

    categories = get_candidate_categories(clf, embedding, top_k=top_k, min_prob=min_prob)
    LOGGER.debug(
        "Routing to categories %s (confidence=%.3f)", categories, conf
    )
    return categories, conf