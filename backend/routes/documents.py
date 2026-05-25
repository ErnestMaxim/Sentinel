from __future__ import annotations

import logging
import os
import shutil
import time
import traceback
from typing import List

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import Document, DocumentStatus, PlagiarismReport
from schemas.documents import DocumentResponse
from routes.auth import get_current_user

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = os.getenv("ML_SHARED_UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_doc_with_report(document_id: int, db: Session) -> Document | None:
    return (
        db.query(Document)
        .options(joinedload(Document.report))
        .filter(
            Document.id == document_id,
            Document.is_deleted == False,  # noqa: E712
        )
        .first()
    )


# ── ML service caller ─────────────────────────────────────────────────────────

def _call_ml_service(file_path: str, arxiv_id: str | None = None) -> dict:
    """Call the ML microservice to run plagiarism analysis."""
    payload = {
        "file_path": file_path,
        "arxiv_id": arxiv_id,
        "threshold": 0.75,
        "top_k": 5,
        "paraphrase_mode": False,
    }

    try:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(f"{ML_SERVICE_URL}/analyze", json=payload)

        if response.status_code == 503:
            raise HTTPException(
                status_code=503,
                detail="ML service is not ready yet (still loading model/artifacts). Try again shortly.",
            )
        if response.status_code == 404:
            raise HTTPException(
                status_code=500,
                detail="ML service could not find the uploaded file. Check shared volume.",
            )
        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"ML service error {response.status_code}: {response.text}",
            )

        return response.json()  # {"result": {...}, "processing_time_seconds": 12.3}

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach ML service at {ML_SERVICE_URL}. Is it running?",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="ML service timed out. The document may be too large.",
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    user_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    file_path = f"{UPLOAD_DIR}/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    new_doc = Document(
        user_id=user_id,
        filename=file.filename,
        file_path=file_path,
        status=DocumentStatus.PENDING,
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    return new_doc


@router.post("/{document_id}/analyze", response_model=DocumentResponse)
def analyze_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    # 1. Verify document exists
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.is_deleted == False,  # noqa: E712
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 2. Return cached result if already analyzed
    existing = db.query(PlagiarismReport).filter(
        PlagiarismReport.document_id == document_id
    ).first()
    if existing:
        return _get_doc_with_report(document_id, db)

    # 3. Mark as processing
    doc.status = DocumentStatus.PROCESSING
    db.commit()

    try:
        logger.info("Sending to ML service: %s", doc.file_path)

        t0 = time.perf_counter()
        ml_response = _call_ml_service(file_path=doc.file_path)
        elapsed = time.perf_counter() - t0

        result = ml_response["result"]
        processing_time = ml_response.get("processing_time_seconds", elapsed)

        logger.info("ML service done in %.2fs — score: %.1f%%",
                    elapsed, result.get("global_plagiarism_score_percent", 0))

        if "error" in result:
            logger.error("ML service returned error: %s", result["error"])
            doc.status = DocumentStatus.FAILED
            db.commit()
            raise HTTPException(status_code=422, detail=result["error"])

        # Save report to DB (same as before)
        report = PlagiarismReport(
            document_id=document_id,
            global_score=result.get("global_plagiarism_score_percent", 0.0),
            report_data=result,
            ai_model_used=result.get("analysis_config", {}).get("embedding_model", "unknown"),
            faiss_index_version="v1.0",
            similarity_threshold=0.75,
            processing_time_seconds=round(processing_time, 3),
        )
        db.add(report)
        doc.word_count = result.get("document_stats", {}).get("total_words")
        doc.status = DocumentStatus.COMPLETED
        db.commit()

        return _get_doc_with_report(document_id, db)

    except HTTPException:
        raise
    except Exception as exc:
        full_tb = traceback.format_exc()
        logger.error("Unexpected error:\n%s", full_tb)
        doc.status = DocumentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"{str(exc)}\n\nTraceback:\n{full_tb}",
        )

@router.get("/", response_model=List[DocumentResponse])
def get_user_documents(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all non-deleted documents (with their reports) for the logged-in user."""
    docs = (
        db.query(Document)
        .options(joinedload(Document.report))
        .filter(
            Document.user_id == current_user.id,
            Document.is_deleted == False,  # noqa: E712
        )
        .order_by(Document.uploaded_at.desc())
        .all()
    )
    return docs

@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = _get_doc_with_report(document_id, db)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc