"""Advanced connection pooling for SQLite database."""

import sqlite3
import threading
import queue
import time
from contextlib import contextmanager
from typing import Generator
from pathlib import Path

from loguru import logger


class ConnectionPool:
    """Thread-safe SQLite connection pool."""
    
    def __init__(self, db_path: Path, pool_size: int = 5, timeout: float = 30.0):
        self.db_path = db_path
        self.pool_size = pool_size
        self.timeout = timeout
        self._connections = queue.Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._created_connections = 0
        
        # Pre-create connections
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the connection pool."""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self._connections.put(conn)
    
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.timeout,
            isolation_level="DEFERRED",
            check_same_thread=False  # Allow sharing between threads
        )
        conn.row_factory = sqlite3.Row
        
        # Optimize connection settings
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")  # 10MB cache
        conn.execute("PRAGMA temp_store=memory")
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
        
        self._created_connections += 1
        logger.debug(f"Created connection #{self._created_connections}")
        
        return conn
    
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection from the pool."""
        conn = None
        start_time = time.time()
        
        try:
            # Get connection from pool
            conn = self._connections.get(timeout=self.timeout)
            
            # Test connection is still valid
            try:
                conn.execute("SELECT 1").fetchone()
            except sqlite3.Error:
                # Connection is broken, create a new one
                logger.warning("Found broken connection, creating new one")
                conn.close()
                conn = self._create_connection()
            
            yield conn
            
        except queue.Empty:
            # Pool exhausted, create temporary connection
            logger.warning("Connection pool exhausted, creating temporary connection")
            conn = self._create_connection()
            
            try:
                yield conn
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"Error getting connection: {e}")
            raise
            
        finally:
            # Return connection to pool
            if conn and self._connections.qsize() < self.pool_size:
                try:
                    self._connections.put_nowait(conn)
                except queue.Full:
                    # Pool is full, close the connection
                    conn.close()
            elif conn:
                # Pool is full or connection is temporary
                conn.close()
            
            elapsed = time.time() - start_time
            if elapsed > 1.0:  # Log slow connections
                logger.warning(f"Slow connection acquisition: {elapsed:.2f}s")
    
    def close_all(self):
        """Close all connections in the pool."""
        with self._lock:
            while not self._connections.empty():
                try:
                    conn = self._connections.get_nowait()
                    conn.close()
                except queue.Empty:
                    break
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")
            
            logger.info(f"Closed all connections in pool")
    
    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "pool_size": self.pool_size,
            "available_connections": self._connections.qsize(),
            "created_connections": self._created_connections,
            "utilization": 1 - (self._connections.qsize() / self.pool_size)
        }


class OptimizedDatabaseManager:
    """Enhanced database manager with connection pooling."""
    
    def __init__(self, db_path: Path = None, pool_size: int = 5):
        self.db_path = db_path or Path("data/indexes/files.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize connection pool
        self.pool = ConnectionPool(self.db_path, pool_size)
        
        # Initialize database schema
        self._init_database()
    
    def _init_database(self):
        """Initialize database with advanced optimizations."""
        with self.pool.get_connection() as conn:
            # Core tables
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
            
            # Advanced indexing strategy
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename)",
                "CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension)",
                "CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type)",
                "CREATE INDEX IF NOT EXISTS idx_files_priority ON files(priority)",
                "CREATE INDEX IF NOT EXISTS idx_files_size ON files(size_bytes)",
                "CREATE INDEX IF NOT EXISTS idx_files_modified ON files(modified_at)",
                "CREATE INDEX IF NOT EXISTS idx_files_parent ON files(parent_dir)",
                "CREATE INDEX IF NOT EXISTS idx_files_composite ON files(file_type, priority, size_bytes)",
                
                # Full-text search
                """CREATE VIRTUAL TABLE IF NOT EXISTS files_fts 
                   USING fts5(path, filename, content_text, content=files)""",
                
                # Triggers to keep FTS in sync
                """CREATE TRIGGER IF NOT EXISTS files_fts_insert AFTER INSERT ON files BEGIN
                   INSERT INTO files_fts(rowid, path, filename, content_text)
                   VALUES(new.id, new.path, new.filename, new.content_text);
                   END""",
                   
                """CREATE TRIGGER IF NOT EXISTS files_fts_delete AFTER DELETE ON files BEGIN
                   DELETE FROM files_fts WHERE rowid = old.id;
                   END""",
                   
                """CREATE TRIGGER IF NOT EXISTS files_fts_update AFTER UPDATE ON files BEGIN
                   UPDATE files_fts SET path=new.path, filename=new.filename, 
                          content_text=new.content_text WHERE rowid=new.id;
                   END"""
            ]
            
            for index_sql in indexes:
                try:
                    conn.execute(index_sql)
                except sqlite3.Error as e:
                    logger.warning(f"Failed to create index: {e}")
            
            # Statistics table
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
            
            # Performance tuning
            conn.execute("ANALYZE")  # Update statistics
            conn.commit()
            
        logger.info("Optimized database initialized with connection pooling")
    
    @contextmanager
    def get_connection(self):
        """Get pooled database connection."""
        with self.pool.get_connection() as conn:
            yield conn
    
    def get_pool_stats(self) -> dict:
        """Get connection pool statistics."""
        return self.pool.get_stats()
    
    def optimize_database(self):
        """Run database optimization tasks."""
        with self.pool.get_connection() as conn:
            logger.info("Starting database optimization...")
            
            # Vacuum to reclaim space and defragment
            conn.execute("VACUUM")
            
            # Update query planner statistics
            conn.execute("ANALYZE")
            
            # Rebuild FTS index
            conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
            
            # Check integrity
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                logger.error(f"Database integrity check failed: {integrity}")
            else:
                logger.info("Database integrity check passed")
            
            conn.commit()
            logger.info("Database optimization completed")
    
    def close(self):
        """Close all connections."""
        self.pool.close_all()