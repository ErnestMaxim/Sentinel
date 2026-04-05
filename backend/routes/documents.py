from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
import shutil
import os

from schemas.documents import DocumentResponse
from models import Document, DocumentStatus
from database import get_db

router = APIRouter(prefix="/documents", tags=["Documents"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    user_id: int = Form(...), # Usually you'd get this from a current_user dependency
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Save the file locally (or to S3 in production)
    file_path = f"{UPLOAD_DIR}/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Create DB record
    new_doc = Document(
        user_id=user_id,
        filename=file.filename,
        file_path=file_path,
        status=DocumentStatus.PENDING
    )
    
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    
    # Here you would typically trigger a background task for the plagiarism check
    # background_tasks.add_task(process_document, new_doc.id)
    
    return new_doc

@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    db_doc = db.query(Document).filter(Document.id == document_id, Document.is_deleted == False).first()
    if db_doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return db_doc