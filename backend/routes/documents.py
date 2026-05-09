from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
import importlib.util
import traceback
import logging
import shutil
import sys
import os
import time
from pathlib import Path

from schemas.documents import DocumentResponse
from models import Document, DocumentStatus, PlagiarismReport
from database import get_db

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── Helper: fetch document + report in one JOIN ───────────────────────────────

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


# ── Engine loader ─────────────────────────────────────────────────────────────

_engine_instance = None


def _load_engine_class():
    this_dir  = Path(__file__).resolve().parent
    engine_py = this_dir.parent / "core" / "antiplagiator" / "engine.py"

    if not engine_py.exists():
        raise FileNotFoundError(f"engine.py not found at: {engine_py}")

    MODULE_NAME = "antiplagiator_engine_module"

    spec   = importlib.util.spec_from_file_location(MODULE_NAME, engine_py)
    module = importlib.util.module_from_spec(spec)

    # CRITICAL: register in sys.modules BEFORE exec_module.
    # @dataclass (and other decorators) call sys.modules.get(cls.__module__)
    # to resolve the module namespace. Without this registration that lookup
    # returns None and crashes with "NoneType has no attribute __dict__".
    sys.modules[MODULE_NAME] = module

    spec.loader.exec_module(module)

    cls = getattr(module, "AntiplagiarismEngine", None)
    if cls is None:
        raise ImportError("AntiplagiarismEngine class not found in engine.py")
    return cls


def get_engine():
    global _engine_instance
    if _engine_instance is None:
        AntiplagiarismEngine = _load_engine_class()
        _engine_instance = AntiplagiarismEngine(
            artifacts_dir=Path("core/antiplagiator/artifacts"),
            data_dir=Path("core/antiplagiator/data/processed"),
        )
    return _engine_instance


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
        logger.info("Loading engine...")
        engine = get_engine()
        logger.info("Engine ready. Analyzing: %s", doc.file_path)

        start  = time.perf_counter()
        result = engine.analyze_document(
            Path(doc.file_path),
            threshold=0.75,
            top_k=5,
        )
        elapsed = time.perf_counter() - start
        logger.info("Analysis complete in %.2fs", elapsed)

        if "error" in result:
            logger.error("Engine returned error: %s", result["error"])
            doc.status = DocumentStatus.FAILED
            db.commit()
            raise HTTPException(status_code=422, detail=result["error"])

        # Save report
        report = PlagiarismReport(
            document_id=document_id,
            global_score=result.get("global_plagiarism_score_percent", 0.0),
            report_data=result,
            ai_model_used=result.get("analysis_config", {}).get("embedding_model", "unknown"),
            faiss_index_version="v1.0",
            similarity_threshold=0.75,
            processing_time_seconds=round(elapsed, 3),
        )
        db.add(report)
        doc.word_count = result.get("document_stats", {}).get("total_words")
        doc.status     = DocumentStatus.COMPLETED
        db.commit()

        return _get_doc_with_report(document_id, db)

    except HTTPException:
        raise
    except Exception as exc:
        full_tb = traceback.format_exc()
        logger.error("Engine error:\n%s", full_tb)
        doc.status = DocumentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"{str(exc)}\n\nTraceback:\n{full_tb}",
        )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = _get_doc_with_report(document_id, db)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc