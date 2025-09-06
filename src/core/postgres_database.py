"""PostgreSQL database manager with pgvector support."""

import os
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text, select, func, and_, or_
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool
import numpy as np
from pgvector.sqlalchemy import Vector

from src.core.models import (
    Base, Document, Tag, Entity, SearchHistory, 
    ProcessingQueue, DuplicateGroup, SystemMetrics, FileStatus
)

logger = logging.getLogger(__name__)


class PostgresDatabase:
    """PostgreSQL database manager with advanced features."""
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize database connection.
        
        Args:
            database_url: PostgreSQL connection URL. If not provided, builds from environment.
        """
        if not database_url:
            database_url = self._build_database_url()
        
        self.database_url = database_url
        
        # Create engine with connection pooling
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=20,
            max_overflow=40,
            pool_pre_ping=True,  # Test connections before using
            echo=False,  # Set to True for SQL debugging
            connect_args={
                "server_settings": {"jit": "off"},  # Disable JIT for better pgvector performance
                "options": "-c statement_timeout=30000"  # 30 second timeout
            }
        )
        
        # Create session factory
        self.SessionLocal = scoped_session(
            sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
        )
        
        # Initialize database
        self._initialize_database()
    
    def _build_database_url(self) -> str:
        """Build database URL from environment variables."""
        from dotenv import load_dotenv
        load_dotenv()
        
        host = os.getenv('POSTGRES_HOST', 'localhost')
        port = os.getenv('POSTGRES_PORT', '5432')
        db = os.getenv('POSTGRES_DB', 'tb36_index')
        user = os.getenv('POSTGRES_USER', 'tb36_user')
        password = os.getenv('POSTGRES_PASSWORD', 'your_secure_password')
        
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    
    def _initialize_database(self):
        """Initialize database with extensions and initial setup."""
        try:
            with self.engine.connect() as conn:
                # Create pgvector extension
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))  # For fuzzy text search
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gin"))  # For composite indexes
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))  # For UUIDs
                conn.commit()
                
            # Create all tables
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database initialized successfully")
            
        except SQLAlchemyError as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    @contextmanager
    def get_session(self):
        """Get a database session with automatic cleanup."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    # Document operations
    
    def add_document(self, file_path: str, **kwargs) -> Document:
        """Add a new document to the database.
        
        Args:
            file_path: Path to the document
            **kwargs: Additional document attributes
            
        Returns:
            Created Document object
        """
        with self.get_session() as session:
            doc = Document(
                path=file_path,
                filename=Path(file_path).name,
                extension=Path(file_path).suffix.lower(),
                **kwargs
            )
            session.add(doc)
            session.flush()
            return doc
    
    def get_document_by_path(self, path: str) -> Optional[Document]:
        """Get document by file path."""
        with self.get_session() as session:
            return session.query(Document).filter(Document.path == path).first()
    
    def get_document_by_id(self, doc_id: int) -> Optional[Document]:
        """Get document by ID."""
        with self.get_session() as session:
            return session.query(Document).filter(Document.id == doc_id).first()
    
    def update_document(self, doc_id: int, **kwargs):
        """Update document attributes."""
        with self.get_session() as session:
            doc = session.query(Document).filter(Document.id == doc_id).first()
            if doc:
                for key, value in kwargs.items():
                    if hasattr(doc, key):
                        setattr(doc, key, value)
                doc.updated_at = datetime.utcnow()
    
    # Vector search operations
    
    def semantic_search(
        self, 
        query_vector: np.ndarray, 
        limit: int = 10,
        threshold: float = 0.7,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[Document, float]]:
        """Perform semantic search using vector similarity.
        
        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results
            threshold: Minimum similarity threshold (0-1)
            filters: Additional filters to apply
            
        Returns:
            List of (Document, similarity_score) tuples
        """
        with self.get_session() as session:
            # Convert numpy array to list for pgvector
            query_vector_list = query_vector.tolist()
            
            # Base query with cosine similarity
            query = session.query(
                Document,
                func.cosine_distance(Document.content_vector, query_vector_list).label('distance')
            ).filter(
                Document.content_vector.isnot(None)
            )
            
            # Apply additional filters
            if filters:
                if 'language' in filters:
                    query = query.filter(Document.language == filters['language'])
                if 'extension' in filters:
                    query = query.filter(Document.extension.in_(filters['extension']))
                if 'category' in filters:
                    query = query.filter(Document.category == filters['category'])
                if 'date_from' in filters:
                    query = query.filter(Document.file_modified_at >= filters['date_from'])
                if 'date_to' in filters:
                    query = query.filter(Document.file_modified_at <= filters['date_to'])
            
            # Order by similarity and apply threshold
            results = query.order_by('distance').limit(limit).all()
            
            # Convert distance to similarity score (1 - distance for cosine)
            return [
                (doc, 1 - float(distance)) 
                for doc, distance in results 
                if 1 - float(distance) >= threshold
            ]
    
    def hybrid_search(
        self,
        text_query: str,
        vector_query: Optional[np.ndarray] = None,
        limit: int = 10,
        text_weight: float = 0.5
    ) -> List[Tuple[Document, float]]:
        """Perform hybrid search combining text and vector search.
        
        Args:
            text_query: Text search query
            vector_query: Optional vector for semantic search
            limit: Maximum number of results
            text_weight: Weight for text search (0-1), remainder for vector
            
        Returns:
            List of (Document, combined_score) tuples
        """
        with self.get_session() as session:
            # Full text search
            text_search = session.query(
                Document,
                func.ts_rank(
                    func.to_tsvector('english', Document.content_text),
                    func.plainto_tsquery('english', text_query)
                ).label('text_rank')
            ).filter(
                func.to_tsvector('english', Document.content_text).op('@@')(
                    func.plainto_tsquery('english', text_query)
                )
            )
            
            if vector_query is not None:
                # Combine with vector search
                vector_list = vector_query.tolist()
                
                # Create subquery for vector similarity
                vector_subq = session.query(
                    Document.id,
                    (1 - func.cosine_distance(Document.content_vector, vector_list)).label('vector_score')
                ).filter(
                    Document.content_vector.isnot(None)
                ).subquery()
                
                # Join and combine scores
                results = session.query(
                    Document,
                    (
                        text_weight * func.coalesce(text_search.subquery().c.text_rank, 0) +
                        (1 - text_weight) * func.coalesce(vector_subq.c.vector_score, 0)
                    ).label('combined_score')
                ).outerjoin(
                    vector_subq, Document.id == vector_subq.c.id
                ).order_by('combined_score').limit(limit).all()
            else:
                # Text search only
                results = text_search.order_by('text_rank').limit(limit).all()
            
            return results
    
    # Duplicate detection
    
    def find_exact_duplicates(self) -> List[DuplicateGroup]:
        """Find exact duplicates based on content hash."""
        with self.get_session() as session:
            # Find documents with same content hash
            duplicates = session.query(
                Document.content_hash,
                func.count(Document.id).label('count'),
                func.array_agg(Document.id).label('doc_ids'),
                func.sum(Document.size_bytes).label('total_size')
            ).filter(
                Document.content_hash.isnot(None)
            ).group_by(
                Document.content_hash
            ).having(
                func.count(Document.id) > 1
            ).all()
            
            groups = []
            for content_hash, count, doc_ids, total_size in duplicates:
                group = DuplicateGroup(
                    group_hash=content_hash,
                    duplicate_type='exact',
                    member_count=count,
                    total_size_bytes=total_size or 0,
                    master_document_id=min(doc_ids)  # Use oldest as master
                )
                session.add(group)
                groups.append(group)
            
            return groups
    
    def find_near_duplicates(self, similarity_threshold: float = 0.95) -> List[DuplicateGroup]:
        """Find near duplicates using vector similarity."""
        with self.get_session() as session:
            # This is computationally expensive, should be done in batches
            docs_with_vectors = session.query(
                Document.id,
                Document.content_vector
            ).filter(
                Document.content_vector.isnot(None)
            ).limit(1000).all()  # Process in batches
            
            groups = []
            processed = set()
            
            for doc_id, doc_vector in docs_with_vectors:
                if doc_id in processed:
                    continue
                
                # Find similar documents
                similar = session.query(
                    Document.id
                ).filter(
                    Document.id != doc_id,
                    Document.content_vector.isnot(None),
                    func.cosine_distance(Document.content_vector, doc_vector) < (1 - similarity_threshold)
                ).all()
                
                if similar:
                    group_ids = [doc_id] + [s[0] for s in similar]
                    processed.update(group_ids)
                    
                    # Create duplicate group
                    group = DuplicateGroup(
                        group_hash=f"near_{doc_id}",
                        duplicate_type='near',
                        member_count=len(group_ids),
                        master_document_id=doc_id
                    )
                    session.add(group)
                    groups.append(group)
            
            return groups
    
    # Statistics and analytics
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self.get_session() as session:
            total_docs = session.query(func.count(Document.id)).scalar()
            total_size = session.query(func.sum(Document.size_bytes)).scalar() or 0
            
            # Documents by status
            status_counts = dict(
                session.query(
                    Document.status,
                    func.count(Document.id)
                ).group_by(Document.status).all()
            )
            
            # Documents by extension
            extension_counts = dict(
                session.query(
                    Document.extension,
                    func.count(Document.id)
                ).group_by(Document.extension).order_by(func.count(Document.id).desc()).limit(10).all()
            )
            
            # Documents by language
            language_counts = dict(
                session.query(
                    Document.language,
                    func.count(Document.id)
                ).filter(Document.language.isnot(None)).group_by(Document.language).all()
            )
            
            return {
                'total_documents': total_docs,
                'total_size_bytes': total_size,
                'total_size_gb': total_size / (1024**3),
                'status_distribution': status_counts,
                'top_extensions': extension_counts,
                'language_distribution': language_counts,
                'has_vectors': session.query(func.count(Document.id)).filter(
                    Document.content_vector.isnot(None)
                ).scalar(),
                'has_text': session.query(func.count(Document.id)).filter(
                    Document.content_text.isnot(None)
                ).scalar(),
            }
    
    # Processing queue management
    
    def add_to_queue(self, document_id: int, task_type: str, priority: int = 5):
        """Add document to processing queue."""
        with self.get_session() as session:
            task = ProcessingQueue(
                document_id=document_id,
                task_type=task_type,
                priority=priority
            )
            session.add(task)
    
    def get_next_task(self, task_type: Optional[str] = None) -> Optional[ProcessingQueue]:
        """Get next task from queue."""
        with self.get_session() as session:
            query = session.query(ProcessingQueue).filter(
                ProcessingQueue.status == 'pending',
                ProcessingQueue.attempts < ProcessingQueue.max_attempts
            )
            
            if task_type:
                query = query.filter(ProcessingQueue.task_type == task_type)
            
            task = query.order_by(
                ProcessingQueue.priority,
                ProcessingQueue.created_at
            ).first()
            
            if task:
                task.status = 'processing'
                task.started_at = datetime.utcnow()
                task.attempts += 1
            
            return task
    
    # Cleanup and maintenance
    
    def vacuum_analyze(self):
        """Run VACUUM ANALYZE for maintenance."""
        with self.engine.connect() as conn:
            conn.execute(text("VACUUM ANALYZE documents"))
            conn.execute(text("VACUUM ANALYZE entities"))
            conn.commit()
    
    def optimize_indexes(self):
        """Reindex for better performance."""
        with self.engine.connect() as conn:
            conn.execute(text("REINDEX TABLE documents"))
            conn.execute(text("REINDEX INDEX idx_documents_content_vector"))
            conn.commit()
    
    def close(self):
        """Close database connections."""
        self.SessionLocal.remove()
        self.engine.dispose()
        logger.info("Database connections closed")