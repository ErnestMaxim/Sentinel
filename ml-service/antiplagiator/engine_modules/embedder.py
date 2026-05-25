from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

LOGGER = logging.getLogger("antiplagiator.embedder")


class Embedder:
    """
    Thin wrapper around SentenceTransformer that adds per-text LRU caching.

    Parameters
    ----------
    model_name : HuggingFace model identifier, e.g. "BAAI/bge-m3"
    device     : "cpu" or "cuda"
    cache_size : maximum number of cached embeddings (default 256)
    """

    def __init__(
        self,
        model_name: str,
        device: str,
        cache_size: int = 256,
    ) -> None:
        LOGGER.info("Loading SentenceTransformer: %s on %s", model_name, device)
        self._model = SentenceTransformer(model_name, device=device)

        # Build a cached encode function bound to this model instance.
        # lru_cache requires a hashable argument, so we cache on the raw string.
        @lru_cache(maxsize=cache_size)
        def _cached_encode(text: str) -> np.ndarray:
            return self._model.encode(
                [text],
                convert_to_numpy=True,
                normalize_embeddings=True,
            )[0]

        self._cached_encode = _cached_encode
        LOGGER.info("Embedder ready.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def encode(self, text: str) -> np.ndarray:
        """Return a normalised embedding vector for a single text (cached)."""
        return self._cached_encode(text)

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        """
        Return a (N, dim) float32 matrix for a list of texts.
        Each text is individually cached so repeated chunks are free.
        """
        return np.vstack([self._cached_encode(t) for t in texts])

    def cache_info(self):
        """Expose lru_cache statistics (hits, misses, currsize)."""
        return self._cached_encode.cache_info()