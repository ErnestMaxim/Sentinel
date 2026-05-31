# ml-service/antiplagiator/engine_modules/remote_index.py
from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
import requests

LOGGER = logging.getLogger("plagiarism_engine.remote_index")


class RemoteIndex:
    """
    Mimics faiss.Index.search() — sends text chunks to Modal for encoding+search
    and returns (similarities, indices) numpy arrays in exactly the format
    the engine expects from a local FAISS index.
    """

    def __init__(
        self,
        base_url: str,
        api_secret: str = "",
        timeout: int = 120,
        default_top_k: int = 20,
    ) -> None:
        self._base_url      = base_url.rstrip("/")
        self._api_secret    = api_secret
        self._timeout       = timeout
        self._default_top_k = default_top_k

        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

        # Pending texts set by engine before calling search()
        self._pending_texts: list[str] = []

        # Grows as results arrive — engine reads self.metadata[db_idx]
        self.metadata: list[dict[str, Any]] = []
        self._key_to_idx: dict[tuple[str, int], int] = {}

        self.ntotal: int = 0
        LOGGER.info("RemoteIndex -> %s", self._base_url)
        self._ping()

    @classmethod
    def from_env(cls) -> "RemoteIndex":
        url = os.getenv("FAISS_REMOTE_URL", "").strip()
        if not url:
            raise RuntimeError(
                "FAISS_REMOTE_URL is not set.\n"
                "Add to ml-service/.env:\n"
                "  FAISS_REMOTE_URL=https://YOUR_WORKSPACE--sentinel-search.modal.run"
            )
        return cls(
            base_url=url,
            api_secret=os.getenv("FAISS_API_SECRET", ""),
            default_top_k=int(os.getenv("FAISS_REMOTE_TOP_K", "20")),
        )

    def _ping(self) -> None:
        health_url = self._base_url.replace("sentinel-search", "sentinel-health")
        try:
            resp = self._session.get(health_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self.ntotal = data.get("total_vectors", 0)
            LOGGER.info(
                "Modal server OK — %d vectors, nprobe=%s",
                self.ntotal, data.get("nprobe"),
            )
        except Exception as e:
            LOGGER.warning("Modal health check failed: %s — continuing anyway", e)

    def set_query_texts(self, texts: list[str]) -> None:
        """
        Called by engine._run_search() before search() so we have the
        original text chunks to send to Modal for encoding.
        """
        self._pending_texts = texts

    def search(
        self,
        query_vectors: np.ndarray,   # float32, shape (n_queries, dim) — ignored, we use texts
        k: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Send text chunks to Modal (which encodes + searches them),
        receive ranked hits back.

        Returns:
            similarities : float32 ndarray (n_queries, k)
            indices      : int64  ndarray (n_queries, k) — local metadata indices
                           -1 = empty slot
        """
        top_k     = k or self._default_top_k
        n_queries = len(query_vectors)

        # Use the texts set by set_query_texts(), then clear them
        texts = self._pending_texts
        self._pending_texts = []

        if not texts:
            LOGGER.error(
                "RemoteIndex.search() called without texts — "
                "engine must call set_query_texts(chunks) first"
            )
            return self._empty(n_queries, top_k)

        payload: dict[str, Any] = {
            "chunks":     texts,
            "top_k":      top_k,
            "threshold":  0.0,        # no pre-filter; engine applies its own
            "api_secret": self._api_secret,
        }

        try:
            resp = self._session.post(
                self._base_url,
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            LOGGER.error("Modal FAISS timed out after %ds", self._timeout)
            return self._empty(n_queries, top_k)
        except requests.exceptions.RequestException as e:
            LOGGER.error("Modal FAISS request failed: %s", e)
            return self._empty(n_queries, top_k)

        data = resp.json()
        LOGGER.info(
            "Modal response: %d chunk results, timing=%.2fs",
            len(data.get("results", [])),
            data.get("timing_s", 0),
        )

        if "error" in data:
            LOGGER.error("Modal error: %s", data["error"])
            return self._empty(n_queries, top_k)

        # Modal returns: {"results": [{"chunk_idx": 0, "hits": [{hit}, ...]}, ...]}
        raw_results: list[dict] = data.get("results", [])

        sims = np.full((n_queries, top_k), -1.0, dtype="float32")
        idxs = np.full((n_queries, top_k), -1,   dtype="int64")

        for chunk_result in raw_results:
            q = int(chunk_result.get("chunk_idx", 0))
            if q >= n_queries:
                continue
            for slot, hit in enumerate(chunk_result.get("hits", [])[:top_k]):
                local_idx = self._register_hit(hit)
                sims[q, slot] = float(hit.get("similarity", -1.0))
                idxs[q, slot] = local_idx

        # Log first chunk top hit for debugging
        if raw_results and raw_results[0].get("hits"):
            top = raw_results[0]["hits"][0]
            LOGGER.info(
                "Top hit: arxiv_id=%s similarity=%.4f",
                top.get("arxiv_id"), top.get("similarity"),
            )

        return sims, idxs

    def _register_hit(self, hit: dict) -> int:
        """Return stable local index for this hit, creating a metadata entry if new."""
        key = (hit.get("arxiv_id", ""), int(hit.get("chunk_id", 0)))
        if key not in self._key_to_idx:
            self._key_to_idx[key] = len(self.metadata)
            self.metadata.append({
                "arxiv_id":     hit.get("arxiv_id", ""),
                "title":        hit.get("title", ""),
                "chunk_id":     hit.get("chunk_id", 0),
                "top_category": hit.get("top_category", ""),
                "source_type":  hit.get("source_type", "unknown"),
                "text":         hit.get("db_text", ""),
            })
        return self._key_to_idx[key]

    @staticmethod
    def _empty(n: int, k: int) -> tuple[np.ndarray, np.ndarray]:
        return (
            np.full((n, k), -1.0, dtype="float32"),
            np.full((n, k), -1,   dtype="int64"),
        )

    def reconstruct_batch(self, *args, **kwargs):
        raise NotImplementedError("reconstruct_batch not available on RemoteIndex")