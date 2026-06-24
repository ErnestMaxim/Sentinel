from __future__ import annotations

import logging
from dataclasses import dataclass

from sentence_transformers import CrossEncoder

LOGGER = logging.getLogger("antiplagiator.reranker")

DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Cross-encoder scores are logits (unbounded).
PARAPHRASE_SCORE_THRESHOLD = 0.0   # logit > 0 means "relevant / semantically similar"
HIGH_CONFIDENCE_THRESHOLD  = 3.0   # logit > 3 means "very likely paraphrase"


@dataclass
class RerankResult:
    """
    A single reranked candidate.

    Attributes
    ----------
    candidate_text  : the database chunk text
    cross_score     : raw logit from the cross-encoder (higher = more similar)
    is_paraphrase   : True when cross_score exceeds PARAPHRASE_SCORE_THRESHOLD
    confidence      : "high" | "medium" | "low" based on score magnitude
    """
    candidate_text: str
    cross_score: float
    is_paraphrase: bool
    confidence: str

    def to_dict(self) -> dict:
        return {
            "candidate_text": self.candidate_text,
            "cross_score":    round(self.cross_score, 4),
            "is_paraphrase":  self.is_paraphrase,
            "confidence":     self.confidence,
        }


def _confidence_label(score: float) -> str:
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if score >= PARAPHRASE_SCORE_THRESHOLD:
        return "medium"
    return "low"


class Reranker:
    """
    Cross-encoder wrapper for paraphrase detection.

    Parameters
    ----------
    model_name : HuggingFace cross-encoder model identifier
    device     : "cpu" or "cuda"
    batch_size : pairs to score in one forward pass (tune to GPU memory)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        LOGGER.info("Loading cross-encoder reranker: %s on %s", model_name, device)
        self._model = CrossEncoder(model_name, device=device)
        self._batch_size = batch_size
        LOGGER.info("Reranker ready.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        candidates: list[str],
        threshold: float = PARAPHRASE_SCORE_THRESHOLD,
    ) -> list[RerankResult]:
        """
        Score all (query, candidate) pairs and return results sorted by score.

        Only candidates with cross_score >= threshold are marked as
        is_paraphrase=True, but all results are returned so the caller
        can inspect the full distribution.

        Parameters
        ----------
        query      : the chunk from the document being checked
        candidates : database chunk texts retrieved by FAISS
        threshold  : logit threshold above which a pair is a paraphrase

        Returns
        -------
        List of RerankResult sorted descending by cross_score.
        """
        if not candidates:
            return []

        pairs = [(query, candidate) for candidate in candidates]
        scores: list[float] = self._model.predict(
            pairs,
            batch_size=self._batch_size,
            show_progress_bar=False,
        ).tolist()

        results = [
            RerankResult(
                candidate_text=candidate,
                cross_score=score,
                is_paraphrase=score >= threshold,
                confidence=_confidence_label(score),
            )
            for candidate, score in zip(candidates, scores)
        ]

        results.sort(key=lambda r: r.cross_score, reverse=True)
        return results

    def is_paraphrase(
        self,
        query: str,
        candidate: str,
        threshold: float = PARAPHRASE_SCORE_THRESHOLD,
    ) -> bool:
        """
        Quick single-pair check. Use rerank() when scoring multiple candidates.
        """
        score = float(self._model.predict([(query, candidate)])[0])
        return score >= threshold

    def best_score(self, query: str, candidates: list[str]) -> float:
        """Return the highest cross-encoder score across all candidates."""
        if not candidates:
            return -999.0
        results = self.rerank(query, candidates)
        return results[0].cross_score if results else -999.0