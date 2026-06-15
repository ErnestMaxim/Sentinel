from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PlagiarismReportResponse(BaseModel):
    id: int
    document_id: int
    global_score: float
    report_data: dict[str, Any]
    ai_model_used: str
    faiss_index_version: str
    similarity_threshold: float
    processing_time_seconds: float | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)