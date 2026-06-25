from __future__ import annotations

import logging
import os
import time
import traceback
import uuid
from pathlib import Path
from typing import List

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from database import get_db, SessionLocal
from models import Document, DocumentStatus, PlagiarismReport
from schemas.documents import DocumentResponse
from routes.auth import get_current_user
from utils.storage import upload_file, get_signed_url
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_doc_with_report(document_id: int, db: Session) -> Document | None:
    return (
        db.query(Document)
        .options(joinedload(Document.report))
        .filter(
            Document.id == document_id,
            Document.is_deleted == False,
        )
        .first()
    )


# ── Background worker ─────────────────────────────────────────────────────────

def _run_analysis(document_id: int, force: bool = False) -> None:
    """Runs in a background thread — owns its own DB session."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(
            Document.id == document_id,
            Document.is_deleted == False,
        ).first()
        if not doc:
            logger.error("Background analysis: document %d not found", document_id)
            return

        existing = db.query(PlagiarismReport).filter(
            PlagiarismReport.document_id == document_id
        ).first()

        if existing and not force:
            return
        if existing and force:
            db.delete(existing)
            db.commit()

        doc.status = DocumentStatus.PROCESSING
        db.commit()

        try:
            logger.info("Background: sending doc %d to ML service: %s", document_id, doc.file_path)
            t0 = time.perf_counter()
            signed_url = get_signed_url(doc.file_path, expires_in=3600)

            payload = {
                "file_url": signed_url,
                "threshold": 0.82,
                "top_k": 10,
                "paraphrase_mode": True,
            }

            with httpx.Client(timeout=600.0) as client:
                response = client.post(f"{ML_SERVICE_URL}/analyze", json=payload)

            elapsed = time.perf_counter() - t0

            if response.status_code == 503:
                raise RuntimeError("ML service not ready yet")
            if response.status_code != 200:
                raise RuntimeError(f"ML service error {response.status_code}: {response.text}")

            ml_response = response.json()
            result = ml_response["result"]
            processing_time = ml_response.get("processing_time_seconds", elapsed)

            logger.info(
                "Background: ML done in %.2fs — score: %.1f%%",
                elapsed, result.get("global_plagiarism_score_percent", 0),
            )

            if "error" in result:
                raise RuntimeError(f"ML returned error: {result['error']}")

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

        except Exception:
            logger.error(
                "Background analysis failed for doc %d:\n%s",
                document_id, traceback.format_exc(),
            )
            doc.status = DocumentStatus.FAILED
            db.commit()

    finally:
        db.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    user_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    suffix    = Path(file.filename).suffix.lower()
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    file_bytes = await file.read()

    new_doc = Document(
        user_id=user_id,
        filename=file.filename,
        file_path="",
        status=DocumentStatus.PENDING,
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    storage_path = f"{new_doc.id}/{safe_name}"
    upload_file(storage_path, file_bytes)

    new_doc.file_path = storage_path
    db.commit()
    db.refresh(new_doc)
    return new_doc

@router.get("/{document_id}/file")
def get_document_file(
    document_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a short-lived signed URL for the original uploaded file and redirect to it."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id,
        Document.is_deleted == False,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path:
        raise HTTPException(status_code=404, detail="File not available")

    signed_url = get_signed_url(doc.file_path, expires_in=300)
    return RedirectResponse(url=signed_url, status_code=302)

@router.post("/{document_id}/analyze", response_model=DocumentResponse)
def analyze_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    force: bool = False,
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.is_deleted == False,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    existing = db.query(PlagiarismReport).filter(
        PlagiarismReport.document_id == document_id
    ).first()
    if existing and not force:
        return _get_doc_with_report(document_id, db)

    if existing and force:
        db.delete(existing)
        db.commit()

    doc.status = DocumentStatus.PROCESSING
    db.commit()

    background_tasks.add_task(_run_analysis, document_id, force)

    return _get_doc_with_report(document_id, db)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    """Poll endpoint — returns current status + report when ready."""
    doc = _get_doc_with_report(document_id, db)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/", response_model=List[DocumentResponse])
def get_user_documents(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all non-deleted documents (with their reports) for the logged-in user."""
    return (
        db.query(Document)
        .options(joinedload(Document.report))
        .filter(
            Document.user_id == current_user.id,
            Document.is_deleted == False,
        )
        .order_by(Document.uploaded_at.desc())
        .all()
    )