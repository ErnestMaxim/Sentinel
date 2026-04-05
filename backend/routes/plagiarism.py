from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from schemas.plagiarism import PlagiarismReportCreate, PlagiarismReportResponse
from models import PlagiarismReport, Document
from database import get_db

router = APIRouter(prefix="/plagiarism", tags=["Plagiarism Reports"])

@router.post("/", response_model=PlagiarismReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(report: PlagiarismReportCreate, db: Session = Depends(get_db)):
    # 1. Verify the document actually exists
    document = db.query(Document).filter(Document.id == report.document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # 2. Ensure we don't create duplicate reports for the same document
    existing_report = db.query(PlagiarismReport).filter(PlagiarismReport.document_id == report.document_id).first()
    if existing_report:
        raise HTTPException(status_code=400, detail="A report already exists for this document")

    # 3. Create the report
    new_report = PlagiarismReport(
        document_id=report.document_id,
        global_score=report.global_score,
        report_data=report.report_data,
        ai_model_used=report.ai_model_used,
        faiss_index_version=report.faiss_index_version,
        similarity_threshold=report.similarity_threshold,
        processing_time_seconds=report.processing_time_seconds
    )
    
    db.add(new_report)
    db.commit()
    db.refresh(new_report)
    return new_report

@router.get("/document/{document_id}", response_model=PlagiarismReportResponse)
def get_report_by_document(document_id: int, db: Session = Depends(get_db)):
    report = db.query(PlagiarismReport).filter(PlagiarismReport.document_id == document_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Plagiarism report not found for this document")
    return report