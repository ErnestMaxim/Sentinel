import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, JSON, Enum
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class DocumentStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)  
    
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False) 
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    added_to_corpus = Column(Boolean, default=False, nullable=False)

    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="documents")
    report = relationship("PlagiarismReport", back_populates="document", uselist=False, cascade="all, delete-orphan")


class PlagiarismReport(Base):
    __tablename__ = "plagiarism_reports"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), unique=True, nullable=False)
    
    global_score = Column(Float, nullable=False)
    report_data = Column(JSON, nullable=False)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    ai_model_used = Column(String, default="all-mpnet-base-v2", nullable=False)
    faiss_index_version = Column(String, default="v1.0", nullable=False)
    similarity_threshold = Column(Float, nullable=False)
    processing_time_seconds = Column(Float, nullable=True)
    
    document = relationship("Document", back_populates="report")