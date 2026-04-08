import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ── Enums ────────────────────────────────────────────────────────────────────

class DocumentStatus(str, enum.Enum):
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"


# ── Models ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id              = Column(Integer,  primary_key=True, index=True)
    first_name      = Column(String,   nullable=False)
    last_name       = Column(String,   nullable=False)
    email           = Column(String,   nullable=False, unique=True, index=True)
    hashed_password = Column(String,   nullable=True)
    google_id       = Column(String,   nullable=True,  unique=True, index=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    is_deleted      = Column(Boolean,  nullable=False, default=False)
    deleted_at      = Column(DateTime, nullable=True)

    documents = relationship("Document", back_populates="user")


class Document(Base):
    __tablename__ = "documents"

    id             = Column(Integer,  primary_key=True, index=True)
    user_id        = Column(Integer,  ForeignKey("users.id"), nullable=False)
    filename       = Column(String,   nullable=False)
    file_path      = Column(String,   nullable=False)
    word_count     = Column(Integer,  nullable=True)
    status         = Column(Enum(DocumentStatus), nullable=False, default=DocumentStatus.PENDING)
    uploaded_at    = Column(DateTime, default=datetime.utcnow)
    added_to_corpus = Column(Boolean, nullable=False, default=False)
    is_deleted     = Column(Boolean,  nullable=False, default=False)
    deleted_at     = Column(DateTime, nullable=True)

    user   = relationship("User",              back_populates="documents")
    report = relationship("PlagiarismReport",  back_populates="document", uselist=False)


class PlagiarismReport(Base):
    __tablename__ = "plagiarism_reports"
    __table_args__ = (UniqueConstraint("document_id"),)

    id                       = Column(Integer,  primary_key=True, index=True)
    document_id              = Column(Integer,  ForeignKey("documents.id"), nullable=False)
    global_score             = Column(Float,    nullable=False)
    report_data              = Column(JSON,     nullable=False)
    created_at               = Column(DateTime, default=datetime.utcnow)
    ai_model_used            = Column(String,   nullable=False)
    faiss_index_version      = Column(String,   nullable=False)
    similarity_threshold     = Column(Float,    nullable=False)
    processing_time_seconds  = Column(Float,    nullable=True)

    document = relationship("Document", back_populates="report")