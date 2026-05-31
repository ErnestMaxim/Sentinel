"""
Sentinel Anti-Plagiarism — Modal.com AI Microservice
=====================================================
Tested with modal==1.4.3

Deploy:
    modal deploy app.py

Download index first (run once):
    modal run app.py::download_index

Test:
    modal run app.py::test_search

Modal Secret (create once):
    modal secret create sentinel-secrets HF_TOKEN=hf_... API_SECRET=some_random_string
"""

from __future__ import annotations

import os
import pickle
import time
from pathlib import Path
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Modal primitives
# ---------------------------------------------------------------------------

app = modal.App("sentinel-faiss-microservice")

volume = modal.Volume.from_name("sentinel-faiss-volume", create_if_missing=True)

VOLUME_MOUNT      = "/data"
INDEX_PATH        = f"{VOLUME_MOUNT}/faiss_document_index.bin"
META_PATH         = f"{VOLUME_MOUNT}/faiss_metadata.pkl"

HF_REPO_ID        = "EXANU/antiplagiator-artifacts"
HF_INDEX_FILENAME = "faiss_document_index.bin"
HF_META_FILENAME  = "faiss_metadata.pkl"
HF_TEXTS_FILENAME = "faiss_texts.pkl"   # list[str] parallel to metadata

TEXTS_PATH = f"{VOLUME_MOUNT}/faiss_texts.pkl"

# ---------------------------------------------------------------------------
# Container image
# ---------------------------------------------------------------------------

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "numpy<2",                       # faiss-cpu 1.8.0 requires NumPy 1.x
        "faiss-cpu==1.8.0",
        "sentence-transformers==3.0.1",
        "huggingface_hub",
        "fastapi",
        "uvicorn",
        "pydantic",
    )
)

# ---------------------------------------------------------------------------
# Download helper — run once to populate the volume
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    memory=8192,
    timeout=3600,
    secrets=[modal.Secret.from_name("faiss-secret")],
)
def download_index():
    """
    Pull FAISS index + metadata from HuggingFace into the Modal volume.
    Only needs to run once. Re-run if you rebuild the index.
    Usage: modal run app.py::download_index
    """
    from huggingface_hub import hf_hub_download

    token = os.environ.get("HF_TOKEN")

    for filename, dest in [
        (HF_INDEX_FILENAME, INDEX_PATH),
        (HF_META_FILENAME,  META_PATH),
        (HF_TEXTS_FILENAME, TEXTS_PATH),
    ]:
        if Path(dest).exists():
            size_gb = Path(dest).stat().st_size / 1024**3
            print(f"[skip] {filename} already in volume ({size_gb:.1f} GB)")
            continue

        print(f"[download] {filename} ...")
        hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=filename,
            repo_type="dataset",
            token=token,
            local_dir=VOLUME_MOUNT,
        )
        size_gb = Path(dest).stat().st_size / 1024**3
        print(f"[done] {filename} ({size_gb:.1f} GB) ✓")

    volume.commit()
    print("Volume committed ✓")


# ---------------------------------------------------------------------------
# Search service — modal 1.4.3 correct decorators
# ---------------------------------------------------------------------------

@app.cls(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    memory=65536,           # 64 GB RAM — fits the full 40 GB IVFFlat index
    cpu=4,
    timeout=300,
    scaledown_window=300,
    min_containers=0,
    secrets=[modal.Secret.from_name("faiss-secret")],
)
@modal.concurrent(max_inputs=5)
class FaissSearchService:

    @modal.enter()
    def load(self):
        import faiss
        from sentence_transformers import SentenceTransformer

        print("[startup] Loading FAISS index ...")
        t0 = time.monotonic()
        self.index = faiss.read_index(INDEX_PATH)
        self.index.nprobe = int(os.environ.get("NPROBE", "20"))
        print(f"[startup] Index ready in {time.monotonic()-t0:.1f}s — {self.index.ntotal:,} vectors")

        print("[startup] Loading metadata ...")
        with open(META_PATH, "rb") as f:
            self.metadata: list[dict[str, Any]] = pickle.load(f)
        print(f"[startup] Metadata ready — {len(self.metadata):,} rows")

        print("[startup] Loading texts ...")
        if Path(TEXTS_PATH).exists():
            with open(TEXTS_PATH, "rb") as f:
                self.texts: list[str] = pickle.load(f)
            print(f"[startup] Texts ready — {len(self.texts):,} entries")
        else:
            self.texts = []
            print("[startup] No texts file found — db_text will be empty")

        print("[startup] Loading embedding model ...")
        self.model = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cpu")
        print("[startup] Ready ✓")

    # ------------------------------------------------------------------
    # Core search logic
    # ------------------------------------------------------------------

    def _search(
        self,
        chunks: list[str],
        top_k: int,
        threshold: float,
        self_arxiv_id: str | None,
        raw_vectors: list[list[float]] | None = None,
    ) -> list[dict[str, Any]]:
        import numpy as np

        if raw_vectors is not None:
            # Pre-encoded vectors sent directly from ml-service — skip encoding
            vectors = np.array(raw_vectors, dtype="float32")
        else:
            vectors = self.model.encode(
                chunks,
                convert_to_numpy=True,
                normalize_embeddings=True,
                batch_size=32,
                show_progress_bar=False,
            ).astype("float32")

        similarities, db_indices = self.index.search(vectors, k=top_k)

        results: list[dict[str, Any]] = []
        for chunk_idx, (scores, indices) in enumerate(zip(similarities, db_indices)):
            chunk_hits: list[dict[str, Any]] = []
            for sim, db_idx in zip(scores, indices):
                sim    = float(sim)
                db_idx = int(db_idx)
                if db_idx < 0 or sim < threshold:
                    continue
                if db_idx >= len(self.metadata):
                    continue
                meta = self.metadata[db_idx]
                if self_arxiv_id and meta.get("arxiv_id") == self_arxiv_id:
                    continue
                db_text = (
                    self.texts[db_idx]
                    if self.texts and db_idx < len(self.texts)
                    else ""
                )
                chunk_hits.append({
                    "db_idx":       db_idx,
                    "similarity":   round(sim, 4),
                    "arxiv_id":     meta.get("arxiv_id", "N/A"),
                    "chunk_id":     meta.get("chunk_id", -1),
                    "title":        meta.get("title", "N/A"),
                    "source_type":  meta.get("source_type", "unknown"),
                    "top_category": meta.get("top_category", ""),
                    "db_text":      db_text,
                })
            results.append({"chunk_idx": chunk_idx, "hits": chunk_hits})

        return results

    # ------------------------------------------------------------------
    # HTTP endpoints — modal 1.4.3 uses @modal.fastapi_endpoint
    # ------------------------------------------------------------------

    @modal.fastapi_endpoint(method="POST", label="sentinel-search")
    def search(self, request: dict) -> dict:
        """
        POST /
        Body:
            {
                "chunks":        ["text 1", "text 2", ...],
                "top_k":         5,
                "threshold":     0.85,
                "self_arxiv_id": "2301.12345",
                "api_secret":    "..."
            }
        """
        expected = os.environ.get("API_SECRET", "")
        if expected and request.get("api_secret", "") != expected:
            return {"error": "Unauthorized", "results": []}

        chunks        = request.get("chunks", [])
        raw_vectors   = request.get("raw_vectors")        # pre-encoded float32 vectors
        top_k         = int(request.get("top_k", 5))
        threshold     = float(request.get("threshold", 0.85))
        self_arxiv_id = request.get("self_arxiv_id")

        if not chunks and raw_vectors is None:
            return {"error": "No chunks or vectors provided", "results": []}

        t0 = time.monotonic()
        results = self._search(chunks, top_k, threshold, self_arxiv_id, raw_vectors)
        elapsed = round(time.monotonic() - t0, 3)

        return {"results": results, "timing_s": elapsed}

    @modal.fastapi_endpoint(method="GET", label="sentinel-health")
    def health(self) -> dict:
        return {
            "status":        "ok",
            "total_vectors": self.index.ntotal,
            "metadata_rows": len(self.metadata),
            "nprobe":        self.index.nprobe,
        }


# ---------------------------------------------------------------------------
# Local test runner
# Usage: modal run app.py::test_search
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def test_search():
    svc = FaissSearchService()

    print("Health check ...")
    print(svc.health.remote())

    print("\nSearch test ...")
    result = svc.search.remote({
        "chunks": ["deep learning for natural language processing"],
        "top_k": 5,
        "threshold": 0.5,
    })
    print(f"timing: {result['timing_s']}s")
    for chunk in result["results"]:
        print(f"\nChunk {chunk['chunk_idx']}: {len(chunk['hits'])} hits")
        for h in chunk["hits"][:3]:
            print(f"  [{h['similarity']:.4f}] {h['arxiv_id']} — {h['title'][:60]}")

@app.function(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    memory=512,
)
def check_volume():
    """Check what files are in the volume and their sizes."""
    import os
    for f in os.listdir(VOLUME_MOUNT):
        path = f"{VOLUME_MOUNT}/{f}"
        size_gb = os.path.getsize(path) / 1024**3
        print(f"  {f}: {size_gb:.3f} GB")
    
    # Also check if texts are actually populated
    import pickle
    texts_path = f"{VOLUME_MOUNT}/faiss_texts.pkl"
    if os.path.exists(texts_path):
        with open(texts_path, "rb") as f:
            texts = pickle.load(f)
        print(f"\nTexts: {len(texts):,} entries")
        print(f"First non-empty: {next((t for t in texts if t), 'ALL EMPTY')[:100]}")
        empty = sum(1 for t in texts if not t)
        print(f"Empty texts: {empty:,} / {len(texts):,}")
    else:
        print("faiss_texts.pkl NOT FOUND in volume")