from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
from models import Document, PlagiarismReport, User
from schemas.plagiarism import PlagiarismReportResponse

router = APIRouter(prefix="/plagiarism", tags=["Plagiarism Reports"])


@router.get("/document/{document_id}", response_model=PlagiarismReportResponse)
def get_report_by_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id,
        Document.is_deleted == False,  # noqa: E712
    ).first()
    if not document:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    report = db.query(PlagiarismReport).filter(
        PlagiarismReport.document_id == document_id
    ).first()
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report found for this document")

    return report