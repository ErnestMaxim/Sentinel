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


HF_TOKEN      = os.getenv("HF_TOKEN")
HF_REPO_ID    = os.getenv("HF_REPO_ID")
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "/data/artifacts"))
DATA_DIR      = Path(os.getenv("DATA_DIR", "/data/processed"))
MODEL_NAME    = os.getenv("MODEL_NAME", "BAAI/bge-base-en-v1.5")
DEVICE        = os.getenv("DEVICE", "auto")

# ── Routing flags (set in .env to enable) ────────────────────────────────────
USE_CATEGORY_ROUTING      = os.getenv("USE_CATEGORY_ROUTING", "true").lower() == "true"
USE_PER_CATEGORY_INDEXES  = os.getenv("USE_PER_CATEGORY_INDEXES", "true").lower() == "true"

if not HF_REPO_ID:
    raise RuntimeError("HF_REPO_ID environment variable is required (e.g. myuser/antiplagiator-artifacts)")


_engine = None


def _load_engine_class():
    """
    Dynamically load AntiplagiarismEngine from engine.py.
    """
    engine_py = Path(__file__).parent / "antiplagiator" / "engine.py"
    if not engine_py.exists():
        raise FileNotFoundError(
            f"engine.py not found at {engine_py}. "
            "Make sure antiplagiator/engine.py exists in ml-service/antiplagiator/"
        )

    MODULE_NAME = "antiplagiator_engine"
    spec   = importlib.util.spec_from_file_location(MODULE_NAME, engine_py)
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
    LOGGER.info("Artifacts dir            : %s", ARTIFACTS_DIR)
    LOGGER.info("HF repo                  : %s", HF_REPO_ID)
    LOGGER.info("Model                    : %s", MODEL_NAME)
    LOGGER.info("Device                   : %s", DEVICE)
    LOGGER.info("Category routing         : %s", USE_CATEGORY_ROUTING)
    LOGGER.info("Per-category indexes     : %s", USE_PER_CATEGORY_INDEXES)
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
        max_sources=200,
        max_matches_per_source=20,
        use_category_routing=USE_CATEGORY_ROUTING,
        use_per_category_indexes=USE_PER_CATEGORY_INDEXES,
    )

    elapsed = time.perf_counter() - t0

    if not _engine.is_ready:
        LOGGER.error("[engine] Failed to initialise: %s", _engine.init_error)
    else:
        LOGGER.info("[engine] Ready in %.1fs", elapsed)

        # Log what routing is active
        if USE_CATEGORY_ROUTING and _engine.clf is not None:
            LOGGER.info("[engine] Classifier loaded — %d classes", len(_engine.clf.classes_))
        else:
            LOGGER.info("[engine] Category routing disabled or classifier not found")

        remote_url = os.getenv("FAISS_REMOTE_URL", "").strip()
        if remote_url:
            LOGGER.info("[engine] Remote Modal index active: %s", remote_url)
            if USE_PER_CATEGORY_INDEXES:
                LOGGER.info(
                    "[engine] Per-category search enabled — "
                    "will call sentinel-search-category endpoint on Modal"
                )
        else:
            LOGGER.info("[engine] Local FAISS index mode")
            if USE_PER_CATEGORY_INDEXES:
                n_cat = len(getattr(_engine, "cat_indexes", {}))
                LOGGER.info("[engine] %d local category indexes loaded", n_cat)

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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    file_path:      str
    arxiv_id:       str | None = None
    threshold:      float = 0.75
    top_k:          int   = 50
    paraphrase_mode: bool = False


class AnalyzeTextRequest(BaseModel):
    text:           str
    label:          str | None = None   # optional tag (e.g. "eval_10pct_cs")
    arxiv_id:       str | None = None
    threshold:      float = 0.75
    top_k:          int   = 50
    paraphrase_mode: bool = False


class AnalyzeResponse(BaseModel):
    result:                  dict[str, Any]
    processing_time_seconds: float


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — reports engine status, routing config, and artifact info."""
    ready = _engine is not None and _engine.is_ready
    routing_info = {}
    if _engine is not None and _engine.is_ready:
        routing_info = {
            "category_routing_enabled": USE_CATEGORY_ROUTING,
            "per_category_indexes":     USE_PER_CATEGORY_INDEXES,
            "classifier_loaded":        _engine.clf is not None,
            "classifier_classes":       (
                list(_engine.clf.classes_) if _engine.clf is not None else []
            ),
            "remote_modal":             bool(os.getenv("FAISS_REMOTE_URL", "").strip()),
        }
    return {
        "status":       "ready" if ready else "not_ready",
        "engine_error": _engine.init_error if _engine and not _engine.is_ready else None,
        "routing":      routing_info,
        "artifacts":    get_artifacts_info(ARTIFACTS_DIR),
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

    LOGGER.info(
        "Analyzing: %s (threshold=%.2f, top_k=%d, routing=%s, per_cat=%s)",
        file_path.name, req.threshold, req.top_k,
        USE_CATEGORY_ROUTING, USE_PER_CATEGORY_INDEXES,
    )

    t0 = time.perf_counter()
    result = _engine.analyze_document(
        file_path,
        threshold=req.threshold,
        top_k=req.top_k,
        arxiv_id=req.arxiv_id,
        paraphrase_mode=req.paraphrase_mode,
    )
    elapsed = round(time.perf_counter() - t0, 3)

    score = result.get("global_plagiarism_score_percent", 0)
    alert = result.get("cross_domain_alert", {})
    LOGGER.info(
        "Done in %.2fs — score: %.1f%%%s",
        elapsed, score,
        " [CROSS-DOMAIN ALERT]" if alert.get("detected") else "",
    )

    return AnalyzeResponse(result=result, processing_time_seconds=elapsed)


@app.post("/analyze_text", response_model=AnalyzeResponse)
def analyze_text(req: AnalyzeTextRequest):
    """
    Evaluate endpoint — accepts raw text instead of a file path.
    Uses mkstemp (safer than NamedTemporaryFile on Windows — no file-lock issues).
    Intended for automated evaluation scripts (Colab, CI, etc.).
    """
    import tempfile, os, traceback as tb
    if _engine is None or not _engine.is_ready:
        raise HTTPException(
            status_code=503,
            detail=f"Engine not ready: {_engine.init_error if _engine else 'still initialising'}",
        )
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text field is empty")

    # mkstemp returns an open OS-level fd — we close it immediately after
    # writing so the engine can open the file without any lock conflicts.
    fd, tmp_name = tempfile.mkstemp(suffix=".txt")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(req.text)
        # fd is now closed — safe for engine to open on Windows
    except Exception:
        os.close(fd)
        tmp_path.unlink(missing_ok=True)
        raise

    try:
        LOGGER.info(
            "analyze_text: label=%s len=%d threshold=%.2f paraphrase=%s",
            req.label or "—", len(req.text), req.threshold, req.paraphrase_mode,
        )
        t0 = time.perf_counter()
        result = _engine.analyze_document(
            tmp_path,
            threshold=req.threshold,
            top_k=req.top_k,
            arxiv_id=req.arxiv_id,
            paraphrase_mode=req.paraphrase_mode,
        )
        elapsed = round(time.perf_counter() - t0, 3)
        if req.label:
            result["eval_label"] = req.label
        LOGGER.info(
            "analyze_text done in %.2fs — score: %.1f%%",
            elapsed, result.get("global_plagiarism_score_percent", 0),
        )
        return AnalyzeResponse(result=result, processing_time_seconds=elapsed)
    except Exception as exc:
        LOGGER.error("analyze_text crashed:\n%s", tb.format_exc())
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Debug routes ──────────────────────────────────────────────────────────────

@app.get("/debug/category/{arxiv_id}")
def debug_category(arxiv_id: str):
    """Check what top_category a paper has in the loaded metadata."""
    if _engine is None or not _engine.is_ready:
        raise HTTPException(status_code=503, detail="Engine not ready")

    matches = [
        {"chunk_id": m.get("chunk_id"), "top_category": m.get("top_category")}
        for m in _engine.metadata
        if arxiv_id in str(m.get("arxiv_id", ""))
    ][:5]

    return {"arxiv_id": arxiv_id, "sample_metadata": matches}


@app.get("/debug/classifier")
def debug_classifier():
    """Show what categories the classifier knows about."""
    if _engine is None or not _engine.is_ready:
        raise HTTPException(status_code=503, detail="Engine not ready")
    if _engine.clf is None:
        return {"error": "Classifier not loaded (routing disabled or file missing)"}
    return {
        "classes":   list(_engine.clf.classes_),
        "n_classes": len(_engine.clf.classes_),
    }


@app.get("/debug/routing")
def debug_routing():
    """Show current routing configuration."""
    if _engine is None or not _engine.is_ready:
        raise HTTPException(status_code=503, detail="Engine not ready")

    remote_url = os.getenv("FAISS_REMOTE_URL", "").strip()
    return {
        "use_category_routing":     USE_CATEGORY_ROUTING,
        "use_per_category_indexes": USE_PER_CATEGORY_INDEXES,
        "classifier_loaded":        _engine.clf is not None,
        "remote_modal_url":         remote_url or None,
        "local_cat_indexes":        list(getattr(_engine, "cat_indexes", {}).keys()),
        "options_active": {
            "option_1_chunk_routing":          USE_CATEGORY_ROUTING and USE_PER_CATEGORY_INDEXES,
            "option_2_confidence_threshold":   USE_CATEGORY_ROUTING and _engine.clf is not None,
            "option_3_cross_domain_alert":     USE_CATEGORY_ROUTING and _engine.clf is not None,
        },
    }


@app.post("/debug/scores")
def debug_scores(req: AnalyzeRequest):
    """Show raw FAISS scores for the first chunk — helps tune threshold."""
    if _engine is None or not _engine.is_ready:
        raise HTTPException(status_code=503, detail="Engine not ready")

    file_path = Path(req.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    chunks, _, _ = _engine._extractor.read_and_chunk(file_path)
    if not chunks:
        return {"error": "No chunks extracted"}

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
            "score":        round(float(score), 4),
            "arxiv_id":     meta.get("arxiv_id"),
            "chunk_id":     meta.get("chunk_id"),
            "top_category": meta.get("top_category"),
        })

    return {
        "first_chunk_preview": first_chunk[:200],
        "top_10_raw_scores":   results,
    }