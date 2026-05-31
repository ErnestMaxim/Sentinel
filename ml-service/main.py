from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import importlib.util
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from artifacts_manager import ensure_artifacts, get_artifacts_info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("ml-service")


HF_TOKEN     = os.getenv("HF_TOKEN")
HF_REPO_ID   = os.getenv("HF_REPO_ID") 
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "/data/artifacts"))
DATA_DIR      = Path(os.getenv("DATA_DIR", "/data/processed"))
MODEL_NAME    = os.getenv("MODEL_NAME", "BAAI/bge-base-en-v1.5")
DEVICE        = os.getenv("DEVICE", "auto")

if not HF_REPO_ID:
    raise RuntimeError("HF_REPO_ID environment variable is required (e.g. myuser/antiplagiator-artifacts)")


_engine = None


def _load_engine_class():
    """
    Dynamically load AntiplagiarismEngine from the engine.py that lives
    alongside this file (copied from backend/core/antiplagiator/).
    """
    engine_py = Path(__file__).parent / "antiplagiator" / "engine.py"
    if not engine_py.exists():
        raise FileNotFoundError(
            f"engine.py not found at {engine_py}. "
            "Make sure you copied backend/core/antiplagiator/ into ml-service/core/antiplagiator/"
        )

    MODULE_NAME = "antiplagiator_engine"
    spec = importlib.util.spec_from_file_location(MODULE_NAME, engine_py)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)

    cls = getattr(module, "AntiplagiarismEngine", None)
    if cls is None:
        raise ImportError("AntiplagiarismEngine not found in engine.py")
    return cls


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine

    LOGGER.info("=" * 60)
    LOGGER.info("ML Service starting up")
    LOGGER.info("Artifacts dir : %s", ARTIFACTS_DIR)
    LOGGER.info("HF repo       : %s", HF_REPO_ID)
    LOGGER.info("Model         : %s", MODEL_NAME)
    LOGGER.info("Device        : %s", DEVICE)
    LOGGER.info("=" * 60)

    # Step 1: ensure artifacts are on disk
    ensure_artifacts(
        artifacts_dir=ARTIFACTS_DIR,
        hf_repo_id=HF_REPO_ID,
        hf_token=HF_TOKEN,
    )

    # Step 2: load the engine
    LOGGER.info("[engine] Loading AntiplagiarismEngine...")
    t0 = time.perf_counter()

    AntiplagiarismEngine = _load_engine_class()
    _engine = AntiplagiarismEngine(
        model_name=MODEL_NAME,
        artifacts_dir=ARTIFACTS_DIR,
        data_dir=DATA_DIR,
        device=DEVICE,
        max_sources=50,
        max_matches_per_source=20,
        use_category_routing=False,
        use_per_category_indexes=False,
    )

    elapsed = time.perf_counter() - t0

    if not _engine.is_ready:
        LOGGER.error("[engine] Failed to initialise: %s", _engine.init_error)
        # Don't crash — /health will report not ready
    else:
        LOGGER.info("[engine] Ready in %.1fs", elapsed)

    yield

    LOGGER.info("ML Service shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Antiplagiator ML Service",
    description="Internal microservice — runs FAISS similarity search and plagiarism scoring",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # internal service — locked down at infra level
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    file_path: str          # absolute path to the uploaded PDF/file (shared volume)
    arxiv_id: str | None = None
    threshold: float = 0.75
    top_k: int = 50
    paraphrase_mode: bool = False


class AnalyzeResponse(BaseModel):
    result: dict[str, Any]
    processing_time_seconds: float


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — also reports engine status and artifact info."""
    ready = _engine is not None and _engine.is_ready
    return {
        "status": "ready" if ready else "not_ready",
        "engine_error": _engine.init_error if _engine and not _engine.is_ready else None,
        "artifacts": get_artifacts_info(ARTIFACTS_DIR),
    }


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    if _engine is None or not _engine.is_ready:
        raise HTTPException(
            status_code=503,
            detail=f"Engine not ready: {_engine.init_error if _engine else 'still initialising'}",
        )

    file_path = Path(req.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found on ML service: {req.file_path}",
        )

    LOGGER.info("Analyzing: %s (threshold=%.2f, top_k=%d)", file_path.name, req.threshold, req.top_k)

    t0 = time.perf_counter()
    result = _engine.analyze_document(
        file_path,
        threshold=req.threshold,
        top_k=req.top_k,
        arxiv_id=req.arxiv_id,
        paraphrase_mode=req.paraphrase_mode,
    )
    elapsed = round(time.perf_counter() - t0, 3)

    LOGGER.info("Done in %.2fs — score: %.1f%%",
                elapsed,
                result.get("global_plagiarism_score_percent", 0))

    return AnalyzeResponse(result=result, processing_time_seconds=elapsed)

@app.get("/debug/category/{arxiv_id}")
def debug_category(arxiv_id: str):
    """Check what top_category a paper has in the loaded metadata."""
    if _engine is None or not _engine.is_ready:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    matches = [
        {"chunk_id": m.get("chunk_id"), "top_category": m.get("top_category")}
        for m in _engine.metadata
        if arxiv_id in str(m.get("arxiv_id", ""))
    ][:5]  # first 5 chunks only
    
    return {"arxiv_id": arxiv_id, "sample_metadata": matches}


@app.get("/debug/classifier")
def debug_classifier():
    if _engine is None or not _engine.is_ready:
        raise HTTPException(status_code=503, detail="Engine not ready")
    return {
        "classes": list(_engine.clf.classes_),
        "n_classes": len(_engine.clf.classes_),
    }

@app.post("/debug/scores")
def debug_scores(req: AnalyzeRequest):
    """Show raw FAISS scores for the first chunk — helps tune threshold."""
    if _engine is None or not _engine.is_ready:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    file_path = Path(req.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    chunks = _engine._extractor.read_and_chunk(file_path)
    if not chunks:
        return {"error": "No chunks extracted"}

    # Encode just the first chunk and search
    import numpy as np
    first_chunk = chunks[0]
    vec = _engine._model.encode(
        [first_chunk],
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype("float32")

    scores, indices = _engine.index.search(vec, 10)
    
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        meta = _engine.metadata[idx] if idx < len(_engine.metadata) else {}
        results.append({
            "score": round(float(score), 4),
            "arxiv_id": meta.get("arxiv_id"),
            "chunk_id": meta.get("chunk_id"),
            "top_category": meta.get("top_category"),
        })

    return {
        "first_chunk_preview": first_chunk[:200],
        "top_10_raw_scores": results,
    }