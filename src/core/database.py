"""Database management for 36TB Intelligence."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
import os
import time

from loguru import logger
from ..scanner.models import FileInfo, FileType, Priority


class DatabaseManager:
    """SQLite database manager for file indexing."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/indexes/files.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Clean up any WAL/SHM files from previous sessions
        self._cleanup_database_files()
        
        self._init_database()
    
    def _cleanup_database_files(self):
        """Clean up WAL and SHM files that might cause locks."""
        try:
            wal_file = Path(str(self.db_path) + "-wal")
            shm_file = Path(str(self.db_path) + "-shm")
            
            # Only clean if files are old (>1 minute)
            current_time = time.time()
            
            if wal_file.exists():
                file_age = current_time - wal_file.stat().st_mtime
                if file_age > 60:  # 1 minute
                    try:
                        wal_file.unlink()
                        logger.info("Cleaned up old WAL file")
                    except OSError:
                        pass
            
            if shm_file.exists():
                file_age = current_time - shm_file.stat().st_mtime
                if file_age > 60:  # 1 minute
                    try:
                        shm_file.unlink()
                        logger.info("Cleaned up old SHM file")
                    except OSError:
                        pass
                        
        except Exception as e:
            logger.debug(f"Could not clean database files: {e}")
    
    def _check_and_unlock_database(self):
        """Check for database locks and attempt to resolve them."""
        try:
            # Try a simple query with short timeout
            with self.get_connection(timeout=5.0, max_retries=1) as conn:
                conn.execute("SELECT 1").fetchone()
            logger.info("Database is accessible")
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.warning("Database appears locked, attempting recovery...")
                
                # Force unlock by trying to open in exclusive mode briefly
                try:
                    conn = sqlite3.connect(str(self.db_path), timeout=1.0)
                    conn.execute("BEGIN IMMEDIATE")
                    conn.rollback()
                    conn.close()
                    logger.info("Database unlock attempt completed")
                except:
                    logger.warning("Could not force unlock, will retry with normal timeouts")
            else:
                raise
    
    def _init_database(self):
        """Initialize database schema with lock checking."""
        # Check for locks first
        self._check_and_unlock_database()
        
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    extension TEXT,
                    size_bytes INTEGER,
                    file_type TEXT,
                    priority TEXT,
                    created_at TEXT,
                    modified_at TEXT,
                    content_text TEXT,
                    content_extracted BOOLEAN DEFAULT 0,
                    metadata TEXT,
                    indexed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    checksum TEXT,
                    parent_dir TEXT,
                    depth INTEGER
                )
            """)
            
            # Create indexes for fast searching
            conn.execute("CREATE INDEX IF NOT EXISTS idx_filename ON files(filename)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extension ON files(extension)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_type ON files(file_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priority ON files(priority)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_size ON files(size_bytes)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_modified ON files(modified_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_parent ON files(parent_dir)")
            
            # Full-text search table
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts 
                USING fts5(path, filename, content_text, content=files)
            """)
            
            # Stats table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scan_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_path TEXT,
                    total_files INTEGER,
                    total_bytes INTEGER,
                    scan_duration REAL,
                    files_per_second REAL,
                    started_at TEXT,
                    completed_at TEXT,
                    metadata TEXT
                )
            """)
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
    
    @contextmanager
    def get_connection(self, timeout=30.0, max_retries=3):
        """Get database connection with timeout and retry logic."""
        # time already imported at module level
        
        for attempt in range(max_retries):
            try:
                # Use timeout and WAL mode for better concurrency
                conn = sqlite3.connect(
                    str(self.db_path), 
                    timeout=timeout,
                    isolation_level="DEFERRED"  # Safe transaction mode
                )
                conn.row_factory = sqlite3.Row
                
                # Enable WAL mode for better concurrent access
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
                conn.execute("PRAGMA synchronous=NORMAL")   # Balance performance/safety
                
                try:
                    yield conn
                    break  # Success, exit retry loop
                finally:
                    conn.close()
                    
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"Database locked, retry {attempt + 1}/{max_retries} in 1s...")
                    time.sleep(1)  # Wait before retry
                    continue
                else:
                    logger.error(f"Database error after {attempt + 1} attempts: {e}")
                    raise
    
    def save_file(self, file_info: FileInfo) -> int:
        """Save a single file to database."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO files (
                    path, filename, extension, size_bytes, file_type, 
                    priority, created_at, modified_at, metadata,
                    parent_dir, depth
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(file_info.path),
                file_info.filename,
                file_info.extension,
                file_info.size_bytes,
                file_info.file_type.value,
                file_info.priority.value,
                file_info.created_at.isoformat() if file_info.created_at else None,
                file_info.modified_at.isoformat() if file_info.modified_at else None,
                json.dumps(file_info.metadata) if file_info.metadata else None,
                str(file_info.path.parent),
                len(file_info.path.parts) - 1
            ))
            conn.commit()
            return cursor.lastrowid
    
    def save_files_batch(self, files: List[FileInfo], batch_size: int = 1000) -> int:
        """Save multiple files in batches."""
        total_saved = 0
        
        with self.get_connection() as conn:
            for i in range(0, len(files), batch_size):
                batch = files[i:i + batch_size]
                data = [
                    (
                        str(f.path),
                        f.filename,
                        f.extension,
                        f.size_bytes,
                        f.file_type.value,
                        f.priority.value,
                        f.created_at.isoformat() if f.created_at else None,
                        f.modified_at.isoformat() if f.modified_at else None,
                        json.dumps(f.metadata) if f.metadata else None,
                        str(f.path.parent),
                        len(f.path.parts) - 1
                    )
                    for f in batch
                ]
                
                conn.executemany("""
                    INSERT OR IGNORE INTO files (
                        path, filename, extension, size_bytes, file_type,
                        priority, created_at, modified_at, metadata,
                        parent_dir, depth
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, data)
                
                total_saved += len(batch)
                
                if total_saved % 5000 == 0:
                    logger.info(f"Saved {total_saved:,} files to database")
            
            conn.commit()
        
        logger.info(f"Total files saved: {total_saved:,}")
        return total_saved
    
    def search_files(
        self,
        query: Optional[str] = None,
        file_type: Optional[FileType] = None,
        priority: Optional[Priority] = None,
        extension: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search files with various filters."""
        
        conditions = []
        params = []
        
        if query:
            # Enhanced text search in filename, path, and content
            conditions.append("(filename LIKE ? OR path LIKE ? OR content_text LIKE ?)")
            search_term = f"%{query}%"
            params.extend([search_term, search_term, search_term])
        
        if file_type:
            conditions.append("file_type = ?")
            # Handle both FileType enum and string
            if hasattr(file_type, 'value'):
                params.append(file_type.value)
            else:
                params.append(str(file_type))
        
        if priority:
            conditions.append("priority = ?")
            # Handle both Priority enum and string
            if hasattr(priority, 'value'):
                params.append(priority.value)
            else:
                params.append(str(priority))
        
        if extension and extension.strip():
            conditions.append("extension = ?")
            params.append(extension.strip().lower())
        
        if min_size is not None:
            conditions.append("size_bytes >= ?")
            params.append(min_size)
        
        if max_size is not None:
            conditions.append("size_bytes <= ?")
            params.append(max_size)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with self.get_connection() as conn:
            # Debug logging
            final_params = params + [limit]
            query_sql = f"""
                SELECT * FROM files
                WHERE {where_clause}
                ORDER BY priority DESC, modified_at DESC
                LIMIT ?
            """
            
            logger.debug(f"Search query: {query_sql}")
            logger.debug(f"Parameters ({len(final_params)}): {final_params}")
            
            try:
                cursor = conn.execute(query_sql, final_params)
            except Exception as e:
                logger.error(f"SQL Error: {e}")
                logger.error(f"Query: {query_sql}")
                logger.error(f"Params: {final_params}")
                logger.error(f"Where clause: {where_clause}")
                logger.error(f"Conditions: {conditions}")
                raise
            
            results = []
            for row in cursor:
                results.append(dict(row))
            
            return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics with error handling."""
        try:
            with self.get_connection() as conn:
                stats = {}
                
                # Total files and size
                cursor = conn.execute("""
                    SELECT COUNT(*), SUM(size_bytes) FROM files
                """)
                count, total_size = cursor.fetchone()
                stats['total_files'] = count or 0
                stats['total_bytes'] = total_size or 0
                stats['total_gb'] = (total_size or 0) / (1024**3)
                
                # Files by type
                cursor = conn.execute("""
                    SELECT file_type, COUNT(*) as count
                    FROM files GROUP BY file_type
                    ORDER BY count DESC
                """)
                stats['by_type'] = {row[0]: row[1] for row in cursor}
                
                # Files by priority
                cursor = conn.execute("""
                    SELECT priority, COUNT(*) as count
                    FROM files GROUP BY priority
                    ORDER BY count DESC
                """)
                stats['by_priority'] = {row[0]: row[1] for row in cursor}
                
                # Top extensions
                cursor = conn.execute("""
                    SELECT extension, COUNT(*) as count
                    FROM files 
                    WHERE extension IS NOT NULL
                    GROUP BY extension
                    ORDER BY count DESC
                    LIMIT 10
                """)
                stats['top_extensions'] = [(row[0], row[1]) for row in cursor]
                
                # Largest files
                cursor = conn.execute("""
                    SELECT filename, size_bytes, path
                    FROM files
                    ORDER BY size_bytes DESC
                    LIMIT 10
                """)
                stats['largest_files'] = [
                    {'filename': row[0], 'size_mb': row[1]/(1024*1024), 'path': row[2]}
                    for row in cursor
                ]
                
                return stats
        
        except Exception as e:
            logger.error(f"Database statistics error: {e}")
            # Return minimal stats on database corruption
            return {
                'total_files': 0,
                'total_bytes': 0,
                'total_gb': 0.0,
                'by_type': {},
                'by_priority': {},
                'top_extensions': [],
                'largest_files': []
            }
    
    def update_content(self, file_id: int, content: str) -> None:
        """Update extracted content for a file."""
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE files 
                SET content_text = ?, content_extracted = 1
                WHERE id = ?
            """, (content, file_id))
            
            # Update FTS index
            conn.execute("""
                INSERT OR REPLACE INTO files_fts (rowid, path, filename, content_text)
                SELECT id, path, filename, ?
                FROM files WHERE id = ?
            """, (content, file_id))
            
            conn.commit()
    
    def get_unprocessed_documents(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get documents that need content extraction."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM files
                WHERE content_extracted = 0
                AND file_type IN ('document', 'email')
                AND size_bytes < 52428800  -- 50MB limit
                ORDER BY priority DESC, size_bytes ASC
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor]
    
    def save_scan_stats(self, stats: Dict[str, Any]) -> None:
        """Save scan statistics."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO scan_stats (
                    scan_path, total_files, total_bytes,
                    scan_duration, files_per_second,
                    started_at, completed_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stats.get('scan_path', 'Unknown'),
                stats.get('total_files', 0),
                stats.get('total_bytes', 0),
                stats.get('scan_duration', 0),
                stats.get('files_per_second', 0),
                stats.get('started_at'),
                stats.get('completed_at'),
                json.dumps(stats.get('metadata', {}))
            ))
            conn.commit()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database stats (alias for get_statistics)."""
        return self.get_statistics()
    
    def get_recent_files(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recently modified files."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM files
                ORDER BY modified_at DESC
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor]