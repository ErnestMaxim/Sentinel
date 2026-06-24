
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
TEXTS_PATH        = f"{VOLUME_MOUNT}/faiss_texts.pkl"
CAT_INDEX_DIR     = f"{VOLUME_MOUNT}/category_indexes"

HF_REPO_ID        = "EXANU/antiplagiator-artifacts"
HF_INDEX_FILENAME = "faiss_document_index.bin"
HF_META_FILENAME  = "faiss_metadata.pkl"
HF_TEXTS_FILENAME = "faiss_texts.pkl"

# ---------------------------------------------------------------------------
# Container image
# ---------------------------------------------------------------------------

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "numpy<2",
        "faiss-cpu==1.8.0",
        "sentence-transformers==3.0.1",
        "huggingface_hub",
        "fastapi",
        "uvicorn",
        "pydantic",
    )
)

# ---------------------------------------------------------------------------
# Download helpers
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
    Pull global FAISS index + metadata + texts from HuggingFace into the Modal volume.
    Only needs to run once. Re-run if you rebuild the global index.
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


@app.function(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    memory=8192,
    timeout=7200,
    secrets=[modal.Secret.from_name("faiss-secret")],
)
def download_category_indexes():
    """
    Pull all per-category FAISS indexes from HuggingFace into the Modal volume.
    Run once after building them with the Colab notebook.
    Usage: modal run app.py::download_category_indexes
    """
    from huggingface_hub import HfApi, hf_hub_download

    token = os.environ.get("HF_TOKEN")
    os.makedirs(CAT_INDEX_DIR, exist_ok=True)

    api = HfApi(token=token)
    all_files = list(api.list_repo_tree(
        repo_id=HF_REPO_ID,
        repo_type="dataset",
        token=token,
        recursive=True,
    ))

    cat_files = [
        f.path for f in all_files
        if hasattr(f, "path") and f.path.startswith("category_indexes/")
    ]

    print(f"Found {len(cat_files)} files in category_indexes/")

    for filename in cat_files:
        dest = f"{VOLUME_MOUNT}/{filename}"
        if Path(dest).exists():
            size_mb = Path(dest).stat().st_size / 1024**2
            print(f"[skip] {filename} already in volume ({size_mb:.0f} MB)")
            continue

        print(f"[download] {filename} ...")
        hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=filename,
            repo_type="dataset",
            token=token,
            local_dir=VOLUME_MOUNT,
        )
        size_mb = Path(dest).stat().st_size / 1024**2
        print(f"[done] {filename} ({size_mb:.0f} MB) ✓")

    volume.commit()
    print(f"\nAll {len(cat_files)} category index files committed to volume ✓")


# ---------------------------------------------------------------------------
# Search service
# ---------------------------------------------------------------------------

@app.cls(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    memory=65536,
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

        # ── Global index ──────────────────────────────────────────────────
        print("[startup] Loading FAISS index ...")
        t0 = time.monotonic()
        # FIX: Added faiss.IO_FLAG_MMAP to instantly memory map the 40GB index
        self.index = faiss.read_index(INDEX_PATH, faiss.IO_FLAG_MMAP)
        self.index.nprobe = int(os.environ.get("NPROBE", "20"))
        print(f"[startup] Index ready in {time.monotonic()-t0:.1f}s — {self.index.ntotal:,} vectors")

        # ── Metadata ──────────────────────────────────────────────────────
        print("[startup] Loading metadata ...")
        with open(META_PATH, "rb") as f:
            self.metadata: list[dict[str, Any]] = pickle.load(f)
        print(f"[startup] Metadata ready — {len(self.metadata):,} rows")

        # ── Texts ─────────────────────────────────────────────────────────
        print("[startup] Loading texts ...")
        if Path(TEXTS_PATH).exists():
            with open(TEXTS_PATH, "rb") as f:
                self.texts: list[str] = pickle.load(f)
            print(f"[startup] Texts ready — {len(self.texts):,} entries")
        else:
            self.texts = []
            print("[startup] No texts file found — db_text will be empty")

        # ── Per-category indexes ───────────────────────────────────────────
        self.cat_indexes:  dict[str, Any] = {}
        self.cat_metadata: dict[str, list[dict]] = {}

        cat_dir = Path(CAT_INDEX_DIR)
        if cat_dir.exists():
            print("[startup] Loading per-category indexes ...")
            t_cat = time.monotonic()
            for bin_file in sorted(cat_dir.glob("faiss_*.bin")):
                meta_file = bin_file.with_name(f"{bin_file.stem}_meta.pkl")
                if not meta_file.exists():
                    print(f"[startup] Missing meta for {bin_file.name} — skipping")
                    continue

                # Key is the category code e.g. "cs", "math", "astro_ph"
                key = bin_file.stem[len("faiss_"):]   # strip "faiss_" prefix
                
                # Added faiss.IO_FLAG_MMAP to safely map the category indexes
                idx = faiss.read_index(str(bin_file), faiss.IO_FLAG_MMAP)
                idx.nprobe = self.index.nprobe

                with open(meta_file, "rb") as f:
                    meta = pickle.load(f)

                # Register under both the safe key and common variants
                self.cat_indexes[key]  = idx
                self.cat_metadata[key] = meta

            print(
                f"[startup] {len(self.cat_indexes)} category indexes ready "
                f"in {time.monotonic()-t_cat:.1f}s"
            )
        else:
            print("[startup] No category_indexes/ directory found — per-category search disabled")

        # ── Embedding model ───────────────────────────────────────────────
        print("[startup] Loading embedding model ...")
        self.model = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cpu")
        print("[startup] Ready ✓")

    # ------------------------------------------------------------------
    # Core search helpers
    # ------------------------------------------------------------------

    def _encode(self, chunks: list[str]) -> "np.ndarray":
        import numpy as np
        return self.model.encode(
            chunks,
            convert_to_numpy=True,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        ).astype("float32")

    def _hits_from_search(
        self,
        vectors: "np.ndarray",
        index: Any,
        metadata: list[dict],
        texts: list[str],
        top_k: int,
        threshold: float,
        self_arxiv_id: str | None,
    ) -> list[dict]:
        """
        Run index.search(), apply threshold + self-filter, return flat list of hits
        grouped by chunk_idx.
        """
        import numpy as np

        similarities, db_indices = index.search(vectors, k=top_k)
        results: list[dict] = []

        for chunk_idx, (scores, indices) in enumerate(zip(similarities, db_indices)):
            chunk_hits: list[dict] = []
            for sim, db_idx in zip(scores, indices):
                sim    = float(sim)
                db_idx = int(db_idx)
                if db_idx < 0 or sim < threshold:
                    continue
                if db_idx >= len(metadata):
                    continue
                meta = metadata[db_idx]
                if self_arxiv_id and meta.get("arxiv_id") == self_arxiv_id:
                    continue
                db_text = (
                    texts[db_idx]
                    if texts and db_idx < len(texts)
                    else meta.get("text", "")
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
    # HTTP endpoints
    # ------------------------------------------------------------------

    @modal.fastapi_endpoint(method="POST", label="sentinel-search")
    def search(self, request: dict) -> dict:
        """
        Global FAISS search across all vectors.

        Body:
            {
                "chunks":        ["text 1", "text 2", ...],
                "top_k":         5,
                "threshold":     0.75,
                "self_arxiv_id": "2301.12345",
                "api_secret":    "..."
            }
        """
        expected = os.environ.get("API_SECRET", "")
        if expected and request.get("api_secret", "") != expected:
            return {"error": "Unauthorized", "results": []}

        chunks        = request.get("chunks", [])
        top_k         = int(request.get("top_k", 5))
        threshold     = float(request.get("threshold", 0.75))
        self_arxiv_id = request.get("self_arxiv_id")

        if not chunks:
            return {"error": "No chunks provided", "results": []}

        t0      = time.monotonic()
        vectors = self._encode(chunks)
        results = self._hits_from_search(
            vectors, self.index, self.metadata, self.texts,
            top_k, threshold, self_arxiv_id,
        )
        elapsed = round(time.monotonic() - t0, 3)

        return {"results": results, "timing_s": elapsed}

    @modal.fastapi_endpoint(method="POST", label="sentinel-search-category")
    def search_category(self, request: dict) -> dict:
        """
        OPTION 1 — Per-chunk category search.
        Searches a specific category sub-index instead of the global index.
        Called by ml-service when route_per_chunk() assigns a chunk to a category.

        Body:
            {
                "chunks":        ["text 1", "text 2", ...],
                "category":      "cs",          # safe key e.g. "cs", "math", "astro_ph"
                "top_k":         5,
                "threshold":     0.75,
                "self_arxiv_id": "2301.12345",
                "api_secret":    "..."
            }

        Response adds "category" field to identify which index was searched.
        Falls back to global search if the category index is not found.
        """
        expected = os.environ.get("API_SECRET", "")
        if expected and request.get("api_secret", "") != expected:
            return {"error": "Unauthorized", "results": []}

        chunks        = request.get("chunks", [])
        category      = str(request.get("category", "")).strip()
        top_k         = int(request.get("top_k", 5))
        threshold     = float(request.get("threshold", 0.75))
        self_arxiv_id = request.get("self_arxiv_id")

        if not chunks:
            return {"error": "No chunks provided", "results": []}

        # ── Resolve category index ────────────────────────────────────────
        safe = category.replace("-", "_").replace(".", "_")
        idx  = self.cat_indexes.get(category) or self.cat_indexes.get(safe)
        meta = self.cat_metadata.get(category) or self.cat_metadata.get(safe)

        t0      = time.monotonic()
        vectors = self._encode(chunks)

        if idx is None or meta is None:
            # Graceful fallback to global index — no error returned
            import logging
            logging.getLogger("modal").warning(
                "No category index for '%s' — falling back to global search", category
            )
            results = self._hits_from_search(
                vectors, self.index, self.metadata, self.texts,
                top_k, threshold, self_arxiv_id,
            )
            used_category = "global_fallback"
        else:
            results = self._hits_from_search(
                vectors, idx, meta, [],
                top_k, threshold, self_arxiv_id,
            )
            used_category = category

        elapsed = round(time.monotonic() - t0, 3)
        return {
            "results":   results,
            "category":  used_category,
            "timing_s":  elapsed,
        }

    @modal.fastapi_endpoint(method="GET", label="sentinel-health")
    def health(self) -> dict:
        return {
            "status":          "ok",
            "total_vectors":   self.index.ntotal,
            "metadata_rows":   len(self.metadata),
            "nprobe":          self.index.nprobe,
            "category_indexes": list(self.cat_indexes.keys()),
        }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    memory=512,
)
def check_volume():
    """Check what files are in the volume and their sizes."""
    import os
    print("Root files:")
    for f in sorted(os.listdir(VOLUME_MOUNT)):
        path = f"{VOLUME_MOUNT}/{f}"
        if os.path.isfile(path):
            size_gb = os.path.getsize(path) / 1024**3
            print(f"  {f}: {size_gb:.3f} GB")
        elif os.path.isdir(path):
            files  = list(Path(path).rglob("*"))
            n      = len([x for x in files if x.is_file()])
            size_gb = sum(x.stat().st_size for x in files if x.is_file()) / 1024**3
            print(f"  {f}/ ({n} files, {size_gb:.2f} GB total)")


@app.local_entrypoint()
def test_search():
    svc = FaissSearchService()

    print("=== Health check ===")
    h = svc.health.remote()
    print(h)

    print("\n=== Global search test ===")
    result = svc.search.remote({
        "chunks": ["deep learning for natural language processing"],
        "top_k": 3,
        "threshold": 0.5,
    })
    print(f"timing: {result['timing_s']}s")
    for chunk in result["results"]:
        print(f"\nChunk {chunk['chunk_idx']}: {len(chunk['hits'])} hits")
        for hit in chunk["hits"][:2]:
            print(f"  [{hit['similarity']:.4f}] {hit['arxiv_id']} — {hit['title'][:60]}")

    print("\n=== Category search test (cs) ===")
    result2 = svc.search_category.remote({
        "chunks": ["neural network training optimization gradient descent"],
        "category": "cs",
        "top_k": 3,
        "threshold": 0.5,
    })
    print(f"category used: {result2.get('category')}  timing: {result2['timing_s']}s")
    for chunk in result2["results"]:
        print(f"\nChunk {chunk['chunk_idx']}: {len(chunk['hits'])} hits")
        for hit in chunk["hits"][:2]:
            print(f"  [{hit['similarity']:.4f}] {hit['arxiv_id']} — {hit['title'][:60]}")