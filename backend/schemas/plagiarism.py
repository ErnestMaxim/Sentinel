from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Any

class PlagiarismReportBase(BaseModel):
    global_score: float
    report_data: dict[str, Any]
    ai_model_used: str = "allenai/specter"
    faiss_index_version: str = "v1.0"
    similarity_threshold: float
    processing_time_seconds: Optional[float] = None

class PlagiarismReportCreate(PlagiarismReportBase):
    document_id: int

class PlagiarismReportResponse(PlagiarismReportBase):
    id: int
    document_id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)