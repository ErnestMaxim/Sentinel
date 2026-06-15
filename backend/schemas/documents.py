from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional
from models import DocumentStatus
from schemas.plagiarism import PlagiarismReportResponse 

class DocumentBase(BaseModel):
    filename: str
    word_count: Optional[int] = None
    status: DocumentStatus = DocumentStatus.PENDING
    added_to_corpus: bool = False

class DocumentCreate(DocumentBase):
    file_path: str
    user_id: int

class DocumentResponse(DocumentBase):
    id: int
    user_id: int
    uploaded_at: datetime
    is_deleted: bool
    report: Optional[PlagiarismReportResponse] = None 
    
    model_config = ConfigDict(from_attributes=True)