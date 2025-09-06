"""SQLAlchemy database models for 36TB Intelligence."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid

from sqlalchemy import (
    Column, String, Integer, BigInteger, Text, DateTime, 
    Boolean, Float, JSON, ForeignKey, Index, Table,
    UniqueConstraint, CheckConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

Base = declarative_base()


# Association tables for many-to-many relationships
document_tags = Table(
    'document_tags',
    Base.metadata,
    Column('document_id', BigInteger, ForeignKey('documents.id', ondelete='CASCADE')),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE')),
    UniqueConstraint('document_id', 'tag_id', name='uq_document_tags')
)

document_relationships = Table(
    'document_relationships',
    Base.metadata,
    Column('source_id', BigInteger, ForeignKey('documents.id', ondelete='CASCADE')),
    Column('target_id', BigInteger, ForeignKey('documents.id', ondelete='CASCADE')),
    Column('relationship_type', String(50)),
    Column('confidence', Float),
    Column('created_at', DateTime, default=datetime.utcnow),
    UniqueConstraint('source_id', 'target_id', 'relationship_type', name='uq_doc_relationships')
)


class FileStatus(str, Enum):
    """File processing status."""
    PENDING = "pending"
    SCANNING = "scanning"
    EXTRACTING = "extracting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    SKIPPED = "skipped"


class Document(Base):
    """Main document table storing all indexed files."""
    __tablename__ = 'documents'
    
    # Primary identification
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    
    # File system information
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    extension: Mapped[Optional[str]] = mapped_column(String(50))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    mime_type: Mapped[Optional[str]] = mapped_column(String(200))
    
    # Timestamps
    file_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    file_modified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    file_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Content and hashing
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # SHA256
    perceptual_hash: Mapped[Optional[str]] = mapped_column(String(64))  # For images
    content_text: Mapped[Optional[str]] = mapped_column(Text)  # Extracted text
    content_summary: Mapped[Optional[str]] = mapped_column(Text)  # AI-generated summary
    
    # Embeddings and vectors
    content_vector: Mapped[Optional[Vector]] = mapped_column(Vector(384))  # For semantic search
    title_vector: Mapped[Optional[Vector]] = mapped_column(Vector(384))  # For title/filename
    
    # Language and encoding
    language: Mapped[Optional[str]] = mapped_column(String(10))
    encoding: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Processing status
    status: Mapped[str] = mapped_column(String(20), default=FileStatus.PENDING.value)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    extraction_version: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Metadata storage
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    extracted_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    
    # Document properties
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    word_count: Mapped[Optional[int]] = mapped_column(Integer)
    has_images: Mapped[bool] = mapped_column(Boolean, default=False)
    has_tables: Mapped[bool] = mapped_column(Boolean, default=False)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_corrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Classification
    category: Mapped[Optional[str]] = mapped_column(String(100))
    subcategory: Mapped[Optional[str]] = mapped_column(String(100))
    importance_score: Mapped[Optional[float]] = mapped_column(Float)
    sensitivity_level: Mapped[Optional[int]] = mapped_column(Integer)  # 1-5 scale
    
    # Relationships
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey('documents.id', ondelete='SET NULL'))
    master_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey('documents.id', ondelete='SET NULL'))
    
    # Relations
    parent = relationship("Document", remote_side=[id], foreign_keys=[parent_id], backref="children")
    master = relationship("Document", remote_side=[id], foreign_keys=[master_id], backref="versions")
    tags = relationship("Tag", secondary=document_tags, back_populates="documents")
    entities = relationship("Entity", back_populates="document", cascade="all, delete-orphan")
    search_history = relationship("SearchHistory", back_populates="document", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_documents_filename', 'filename'),
        Index('idx_documents_extension', 'extension'),
        Index('idx_documents_status', 'status'),
        Index('idx_documents_category', 'category'),
        Index('idx_documents_language', 'language'),
        Index('idx_documents_file_modified', 'file_modified_at'),
        Index('idx_documents_indexed', 'indexed_at'),
        Index('idx_documents_content_hash', 'content_hash'),
        Index('idx_documents_parent', 'parent_id'),
        Index('idx_documents_master', 'master_id'),
        # Vector indexes for similarity search
        Index('idx_documents_content_vector', 'content_vector', postgresql_using='ivfflat', 
              postgresql_ops={'content_vector': 'vector_cosine_ops'}),
        Index('idx_documents_title_vector', 'title_vector', postgresql_using='ivfflat',
              postgresql_ops={'title_vector': 'vector_cosine_ops'}),
        # Full text search index
        Index('idx_documents_fts', func.to_tsvector('english', 'content_text'), postgresql_using='gin'),
        # JSONB indexes
        Index('idx_documents_metadata', 'metadata', postgresql_using='gin'),
        Index('idx_documents_extracted_metadata', 'extracted_metadata', postgresql_using='gin'),
    )


class Tag(Base):
    """Tags for document categorization."""
    __tablename__ = 'tags'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    color: Mapped[Optional[str]] = mapped_column(String(7))  # Hex color
    icon: Mapped[Optional[str]] = mapped_column(String(50))
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('tags.id', ondelete='CASCADE'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relations
    parent = relationship("Tag", remote_side=[id], backref="children")
    documents = relationship("Document", secondary=document_tags, back_populates="tags")
    
    __table_args__ = (
        Index('idx_tags_name', 'name'),
        Index('idx_tags_parent', 'parent_id'),
    )


class Entity(Base):
    """Named entities extracted from documents."""
    __tablename__ = 'entities'
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # PERSON, ORG, LOCATION, DATE, MONEY, etc.
    entity_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    start_position: Mapped[Optional[int]] = mapped_column(Integer)
    end_position: Mapped[Optional[int]] = mapped_column(Integer)
    context: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relations
    document = relationship("Document", back_populates="entities")
    
    __table_args__ = (
        Index('idx_entities_document', 'document_id'),
        Index('idx_entities_type', 'entity_type'),
        Index('idx_entities_value', 'entity_value'),
        Index('idx_entities_normalized', 'normalized_value'),
    )


class SearchHistory(Base):
    """Track all searches for analytics and improvement."""
    __tablename__ = 'search_history'
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_type: Mapped[str] = mapped_column(String(50))  # literal, semantic, visual, etc.
    query_vector: Mapped[Optional[Vector]] = mapped_column(Vector(384))
    user_id: Mapped[Optional[str]] = mapped_column(String(100))
    session_id: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Results
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    clicked_result_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey('documents.id', ondelete='SET NULL'))
    clicked_position: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Performance
    search_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Metadata
    filters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relations
    document = relationship("Document", back_populates="search_history")
    
    __table_args__ = (
        Index('idx_search_history_timestamp', 'timestamp'),
        Index('idx_search_history_user', 'user_id'),
        Index('idx_search_history_session', 'session_id'),
        Index('idx_search_history_query_type', 'query_type'),
    )


class ProcessingQueue(Base):
    """Queue for managing document processing tasks."""
    __tablename__ = 'processing_queue'
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)  # extract, embed, ocr, etc.
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1-10, lower is higher priority
    status: Mapped[str] = mapped_column(String(20), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    
    # Timing
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Error tracking
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    
    # Worker info
    worker_id: Mapped[Optional[str]] = mapped_column(String(100))
    
    __table_args__ = (
        Index('idx_queue_status_priority', 'status', 'priority'),
        Index('idx_queue_document', 'document_id'),
        Index('idx_queue_task_type', 'task_type'),
        Index('idx_queue_created', 'created_at'),
    )


class DuplicateGroup(Base):
    """Groups of duplicate documents."""
    __tablename__ = 'duplicate_groups'
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    duplicate_type: Mapped[str] = mapped_column(String(20))  # exact, near, semantic
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    master_document_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey('documents.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    action_taken: Mapped[Optional[str]] = mapped_column(String(50))  # keep_all, keep_master, delete_duplicates
    
    __table_args__ = (
        Index('idx_duplicate_groups_hash', 'group_hash'),
        Index('idx_duplicate_groups_type', 'duplicate_type'),
        Index('idx_duplicate_groups_reviewed', 'reviewed'),
    )


class SystemMetrics(Base):
    """System performance and usage metrics."""
    __tablename__ = 'system_metrics'
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_metrics_type_name', 'metric_type', 'metric_name'),
        Index('idx_metrics_timestamp', 'timestamp'),
    )