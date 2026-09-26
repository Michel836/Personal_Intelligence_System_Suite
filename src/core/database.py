"""Database management for 36TB Intelligence."""

import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
import os
import time

from loguru import logger
from ..scanner.models import EXTRACTION_LIMIT, FileInfo, FileType, Priority
from .volume import VolumeInfo, normalize_root, resolve_volume, roots_overlap


def default_db_path() -> str:
    """Resolve the configured index DB path (``PIS_DB_PATH`` or default)."""
    return os.environ.get("PIS_DB_PATH") or "data/indexes/files.db"


# --- Lexical search (FTS5) -------------------------------------------------
#
# The FTS index is external-content (``content=files``), so it must be kept in
# sync by triggers. ``bm25`` provides lexical relevance; ties are broken by a
# semantic priority rank, then modification time and finally id so ordering is
# deterministic.
FTS_SCHEMA_VERSION = "1"
_PRIORITY_RANK_SQL = (
    "CASE priority "
    "WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
    "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END"
)
# Unicode-aware word characters (letters, digits, underscore and non-Latin
# scripts). This preserves accented terms such as "résumé" while still
# discarding FTS operators/punctuation.
_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_FTS_SEGMENT_RE = re.compile(r'"([^"]*)"|(\S+)')
# Single-character terms are matched exactly; only length >= 2 terms may use a
# prefix query, otherwise "c++"/"C#" would broaden to every token starting "c".
_FTS_MIN_PREFIX_LENGTH = 2


def build_fts_match(query: str) -> Optional[str]:
    """Build a safe FTS5 MATCH expression from user input.

    Plain terms become prefix queries (length >= 2) combined with implicit AND;
    quoted segments become exact phrases. Tokenisation is Unicode-aware and
    operators are neutralised by extracting word characters and quoting, so
    malformed input cannot raise an FTS syntax error. Returns ``None`` when no
    usable term remains.
    """
    terms: List[str] = []
    for phrase, bare in _FTS_SEGMENT_RE.findall(query):
        if phrase:
            tokens = _FTS_TOKEN_RE.findall(phrase)
            if tokens:
                terms.append('"' + " ".join(tokens) + '"')
        else:
            for token in _FTS_TOKEN_RE.findall(bare):
                if len(token) >= _FTS_MIN_PREFIX_LENGTH:
                    terms.append(f'"{token}"*')
                else:
                    terms.append(f'"{token}"')
    return " ".join(terms) if terms else None


class DatabaseManager:
    """SQLite database manager for file indexing."""
    
    def __init__(self, db_path: Optional[Path] = None):
        # ``PIS_DB_PATH`` lets tests/acceptance point the application at a
        # temporary database without touching the default repo index.
        self.db_path = Path(db_path) if db_path is not None else Path(default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # SQLite owns the WAL/SHM lifecycle. The harness must never unlink
        # ``-wal``/``-shm`` itself: doing so can corrupt or lock a database that
        # another connection is actively using.
        self._init_database()

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
            
            # Full-text search table + canonical synchronisation triggers
            self._ensure_fts(conn)

            # Volume / scan-run / lifecycle state
            self._ensure_lifecycle(conn)

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

    def _ensure_fts(self, conn) -> None:
        """Create the FTS table/triggers and rebuild the index when needed.

        An external-content FTS index stays empty until it is explicitly
        populated, so metadata-only databases (created before trigger support)
        are rebuilt once per schema version. The triggers keep it synchronised
        afterwards, preventing silent stale-index state.
        """
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts
            USING fts5(path, filename, content_text, content=files)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fts_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Recreate the canonical triggers so exactly one lifecycle exists (this
        # also replaces the buggy plain UPDATE/DELETE variants).
        for trigger in ("files_fts_insert", "files_fts_delete", "files_fts_update"):
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")

        conn.execute("""
            CREATE TRIGGER files_fts_insert AFTER INSERT ON files BEGIN
                INSERT INTO files_fts(rowid, path, filename, content_text)
                VALUES (new.id, new.path, new.filename, new.content_text);
            END
        """)
        conn.execute("""
            CREATE TRIGGER files_fts_delete AFTER DELETE ON files BEGIN
                INSERT INTO files_fts(files_fts, rowid, path, filename, content_text)
                VALUES ('delete', old.id, old.path, old.filename, old.content_text);
            END
        """)
        conn.execute("""
            CREATE TRIGGER files_fts_update AFTER UPDATE OF path, filename, content_text ON files BEGIN
                INSERT INTO files_fts(files_fts, rowid, path, filename, content_text)
                VALUES ('delete', old.id, old.path, old.filename, old.content_text);
                INSERT INTO files_fts(rowid, path, filename, content_text)
                VALUES (new.id, new.path, new.filename, new.content_text);
            END
        """)

        row = conn.execute(
            "SELECT value FROM fts_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None or row[0] != FTS_SCHEMA_VERSION:
            conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
            conn.execute(
                "INSERT OR REPLACE INTO fts_meta(key, value) VALUES ('schema_version', ?)",
                (FTS_SCHEMA_VERSION,),
            )
            logger.info("Rebuilt FTS index for existing database")

    # --- Volume / scan-run lifecycle -------------------------------------
    #
    # Invariants enforced here:
    #  * absence of a path during an incomplete/failed/cancelled scan is NOT
    #    proof of deletion (reconciliation only runs on COMPLETED runs);
    #  * a missing/unavailable volume never causes reconciliation;
    #  * lifecycle changes are reversible (rows are never physically deleted);
    #    files transition ACTIVE <-> MISSING.
    def _ensure_lifecycle(self, conn) -> None:
        """Create lifecycle tables/columns, preserving all existing rows."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS volumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stable_key TEXT UNIQUE NOT NULL,
                device TEXT,
                fs_uuid TEXT,
                fs_type TEXT,
                mountpoint TEXT,
                display_name TEXT,
                is_available INTEGER DEFAULT 0,
                identity_verified INTEGER DEFAULT 0,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                volume_id INTEGER,
                root_path TEXT NOT NULL,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                files_seen INTEGER DEFAULT 0,
                files_upserted INTEGER DEFAULT 0,
                files_errors INTEGER DEFAULT 0,
                error_message TEXT
            )
        """)
        volume_columns = {row[1] for row in conn.execute("PRAGMA table_info(volumes)")}
        if "identity_verified" not in volume_columns:
            conn.execute("ALTER TABLE volumes ADD COLUMN identity_verified INTEGER DEFAULT 0")
        existing = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
        columns = {
            "volume_id": "INTEGER",
            "last_seen_scan_id": "INTEGER",
            "state": "TEXT DEFAULT 'ACTIVE'",
            "device_id": "INTEGER",
            "inode": "INTEGER",
        }
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE files ADD COLUMN {name} {decl}")
                logger.info(f"Added files.{name} for lifecycle tracking")
        conn.execute("UPDATE files SET state = 'ACTIVE' WHERE state IS NULL OR state = ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_volume ON files(volume_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_state ON files(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_last_seen ON files(last_seen_scan_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_identity ON files(volume_id, device_id, inode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_runs_volume ON scan_runs(volume_id)")

    def _upsert_volume(self, conn, volume: VolumeInfo) -> int:
        conn.execute("""
            INSERT INTO volumes (stable_key, device, fs_uuid, fs_type, mountpoint,
                                 display_name, is_available, identity_verified, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(stable_key) DO UPDATE SET
                device = excluded.device,
                fs_uuid = excluded.fs_uuid,
                fs_type = excluded.fs_type,
                mountpoint = excluded.mountpoint,
                display_name = excluded.display_name,
                is_available = excluded.is_available,
                identity_verified = excluded.identity_verified,
                last_seen_at = CURRENT_TIMESTAMP
        """, (
            volume.stable_key, volume.device, volume.fs_uuid, volume.fs_type,
            volume.mountpoint, volume.display_name or volume.mountpoint,
            1 if volume.is_available else 0,
            1 if volume.identity_verified else 0,
        ))
        row = conn.execute(
            "SELECT id FROM volumes WHERE stable_key = ?", (volume.stable_key,)
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _run_row(conn, run_id: int):
        return conn.execute("SELECT * FROM scan_runs WHERE id = ?", (run_id,)).fetchone()

    @staticmethod
    def _volume_row(conn, volume_id: int):
        return conn.execute("SELECT * FROM volumes WHERE id = ?", (volume_id,)).fetchone()

    def begin_scan(self, root_path, *, volume: Optional[VolumeInfo] = None) -> dict:
        """Start a RUNNING scan run for a normalized root/volume.

        Raises ``ValueError`` when another RUNNING run on the same volume has an
        overlapping root scope.
        """
        root = normalize_root(root_path)
        resolved = volume or resolve_volume(root)
        with self.get_connection() as conn:
            volume_id = self._upsert_volume(conn, resolved)
            for row in conn.execute(
                "SELECT id, volume_id, root_path FROM scan_runs WHERE status = 'RUNNING'"
            ).fetchall():
                if row["volume_id"] == volume_id and roots_overlap(root, row["root_path"]):
                    raise ValueError(
                        f"overlapping RUNNING scan: run {row['id']} already covers {row['root_path']}"
                    )
            cursor = conn.execute(
                "INSERT INTO scan_runs (volume_id, root_path, started_at, status) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, 'RUNNING')",
                (volume_id, root),
            )
            run_id = int(cursor.lastrowid)
            conn.commit()
        return {"run_id": run_id, "volume_id": volume_id, "root_path": root, "volume": resolved}

    def record_scan_files(self, run_id: int, files: List[FileInfo]) -> int:
        """Upsert files under a run, stamping volume / last_seen / ACTIVE."""
        with self.get_connection() as conn:
            run = self._run_row(conn, run_id)
            if run is None:
                raise ValueError(f"unknown scan run {run_id}")
            if run["status"] != "RUNNING":
                raise ValueError(f"scan run {run_id} is {run['status']}, not RUNNING")
            volume_id = int(run["volume_id"])
        upserted = self.save_files_batch(files, volume_id=volume_id, scan_id=run_id)
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE scan_runs SET files_seen = files_seen + ?, "
                "files_upserted = files_upserted + ? WHERE id = ?",
                (len(files), upserted, run_id),
            )
            conn.commit()
        return upserted

    def _finish_run(self, run_id: int, status: str, *, error_message: Optional[str] = None) -> None:
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE scan_runs SET status = ?, finished_at = CURRENT_TIMESTAMP, "
                "error_message = ? WHERE id = ?",
                (status, error_message, run_id),
            )
            conn.commit()

    def fail_scan(self, run_id: int, error_message: Optional[str] = None) -> None:
        """Mark a run FAILED. Never reconciles."""
        self._finish_run(run_id, "FAILED", error_message=error_message)

    def cancel_scan(self, run_id: int) -> None:
        """Mark a run CANCELLED. Never reconciles."""
        self._finish_run(run_id, "CANCELLED")

    def recover_stale_runs(self, *, status: str = "FAILED") -> int:
        """Mark leftover RUNNING runs terminal on process startup.

        A run that was RUNNING when a previous process died can never be
        completed safely, so it must not reconcile. Call this only at startup
        (before starting new scans) so a live run is never touched.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE scan_runs SET status = ?, finished_at = CURRENT_TIMESTAMP, "
                "error_message = COALESCE(error_message, "
                "'abandoned RUNNING run recovered at startup') "
                "WHERE status = 'RUNNING'",
                (status,),
            )
            conn.commit()
            return int(cursor.rowcount)

    def complete_scan(self, run_id: int) -> dict:
        """Mark a run COMPLETED and reconcile its scope (rename + MISSING).

        Reconciliation only happens for a RUNNING run whose volume is currently
        available; otherwise a ValueError is raised and nothing changes.
        """
        with self.get_connection() as conn:
            run = self._run_row(conn, run_id)
            if run is None:
                raise ValueError(f"unknown scan run {run_id}")
            if run["status"] != "RUNNING":
                raise ValueError(f"scan run {run_id} is {run['status']}, not RUNNING")
            volume = self._volume_row(conn, int(run["volume_id"]))
            available = volume is not None and bool(volume["is_available"])
            root_path = run["root_path"]
            registered_key = volume["stable_key"] if volume else None
            verify_identity = bool(volume["identity_verified"]) if volume else False

        if not available:
            # Never leave a stuck RUNNING run behind; a FAILED run never
            # reconciles, so files keep their previous lifecycle state.
            self._finish_run(run_id, "FAILED", error_message="volume unavailable")
            raise ValueError("refusing to reconcile: volume is not available")

        if verify_identity:
            # The same mountpoint may now belong to a different device (disk
            # swapped/unmounted). Never reconcile unless the resolved identity
            # still matches the volume that was scanned.
            resolved = resolve_volume(root_path)
            if not resolved.is_available or resolved.stable_key != registered_key:
                self._finish_run(run_id, "FAILED", error_message="volume identity mismatch")
                raise ValueError("refusing to reconcile: volume identity changed")

        self._finish_run(run_id, "COMPLETED")
        with self.get_connection() as conn:
            renamed = self._associate_renames(conn, run_id)
            missing = self._mark_missing(conn, run_id)
            conn.commit()
        return {"run_id": run_id, "renamed": renamed, "missing": missing}

    @staticmethod
    def _like_scope(root: str) -> str:
        escaped = root.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return escaped.rstrip(os.sep) + os.sep + "%"

    @classmethod
    def _scope_clause(cls, column: str) -> str:
        return f"({column} = ? OR {column} LIKE ? ESCAPE '\\')"

    def _mark_missing(self, conn, run_id: int) -> int:
        run = self._run_row(conn, run_id)
        root = run["root_path"]
        cursor = conn.execute(
            f"""UPDATE files SET state = 'MISSING'
                WHERE volume_id = ?
                  AND state = 'ACTIVE'
                  AND (last_seen_scan_id IS NULL OR last_seen_scan_id != ?)
                  AND {self._scope_clause('path')}""",
            (run["volume_id"], run_id, root, self._like_scope(root)),
        )
        return int(cursor.rowcount)

    def _associate_renames(self, conn, run_id: int) -> int:
        run = self._run_row(conn, run_id)
        root = run["root_path"]
        like = self._like_scope(root)
        rows = conn.execute(
            f"""SELECT old.id AS old_id, new.id AS new_id, new.path AS new_path
                FROM files AS old
                JOIN files AS new
                  ON new.volume_id = old.volume_id
                 AND new.device_id = old.device_id
                 AND new.inode = old.inode
                 AND new.size_bytes = old.size_bytes
                 AND new.last_seen_scan_id = ?
                 AND new.state = 'ACTIVE'
                 AND new.id != old.id
                WHERE old.volume_id = ?
                  AND old.state = 'ACTIVE'
                  AND (old.last_seen_scan_id IS NULL OR old.last_seen_scan_id != ?)
                  AND old.device_id IS NOT NULL
                  AND old.inode IS NOT NULL
                  AND {self._scope_clause('old.path')}
                  AND {self._scope_clause('new.path')}""",
            (run_id, run["volume_id"], run_id, root, like, root, like),
        ).fetchall()
        if not rows:
            return 0
        old_counts: dict[int, int] = {}
        new_counts: dict[int, int] = {}
        for row in rows:
            old_counts[row["old_id"]] = old_counts.get(row["old_id"], 0) + 1
            new_counts[row["new_id"]] = new_counts.get(row["new_id"], 0) + 1
        applied = 0
        for row in rows:
            if old_counts[row["old_id"]] != 1 or new_counts[row["new_id"]] != 1:
                continue
            new_path = row["new_path"]
            # Remove the freshly-inserted duplicate first (path is UNIQUE), then
            # rewrite the surviving row onto the new path so row id and any
            # extracted content/checksum are preserved.
            conn.execute("DELETE FROM files WHERE id = ?", (row["new_id"],))
            conn.execute(
                """UPDATE files SET
                       path = ?, filename = ?, extension = ?, parent_dir = ?,
                       depth = ?, last_seen_scan_id = ?, state = 'ACTIVE',
                       indexed_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (
                    new_path, os.path.basename(new_path),
                    os.path.splitext(new_path)[1].lower(), os.path.dirname(new_path),
                    new_path.count(os.sep), run_id, row["old_id"],
                ),
            )
            applied += 1
        return applied

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
    
    # Invariant: absence of a path during an unqualified (partial, cancelled or
    # volume-disconnected) scan is NOT proof of deletion. Deletion/rename/move
    # reconciliation is intentionally not implemented here and belongs to a
    # later mission with volume identity and completed scan-run boundaries.
    def save_file(self, file_info: FileInfo, *, volume_id: Optional[int] = None,
                  scan_id: Optional[int] = None) -> int:
        """Insert or refresh a file's scan metadata, returning its row id.

        Existing extracted content (``content_text``/``content_extracted``) is
        preserved; only scanner-owned metadata is refreshed. When ``scan_id`` is
        supplied the row is stamped with ``volume_id``/``last_seen_scan_id`` and
        ``state='ACTIVE'`` (a completed scan run may later reconcile it).
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO files (
                    path, filename, extension, size_bytes, file_type,
                    priority, created_at, modified_at, metadata,
                    parent_dir, depth, checksum,
                    volume_id, last_seen_scan_id, state, device_id, inode, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(path) DO UPDATE SET
                    filename = excluded.filename,
                    extension = excluded.extension,
                    size_bytes = excluded.size_bytes,
                    file_type = excluded.file_type,
                    priority = excluded.priority,
                    created_at = COALESCE(excluded.created_at, files.created_at),
                    modified_at = excluded.modified_at,
                    metadata = excluded.metadata,
                    parent_dir = excluded.parent_dir,
                    depth = excluded.depth,
                    checksum = COALESCE(excluded.checksum, files.checksum),
                    volume_id = COALESCE(excluded.volume_id, files.volume_id),
                    last_seen_scan_id = COALESCE(excluded.last_seen_scan_id, files.last_seen_scan_id),
                    state = CASE WHEN excluded.last_seen_scan_id IS NOT NULL THEN 'ACTIVE' ELSE files.state END,
                    device_id = COALESCE(excluded.device_id, files.device_id),
                    inode = COALESCE(excluded.inode, files.inode),
                    indexed_at = CURRENT_TIMESTAMP
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
                len(file_info.path.parts) - 1,
                file_info.checksum or None,
                volume_id,
                scan_id,
                "ACTIVE",
                file_info.device_id,
                file_info.inode,
            ))
            conn.commit()
            row = conn.execute(
                "SELECT id FROM files WHERE path = ?", (str(file_info.path),)
            ).fetchone()
            return int(row[0]) if row else int(cursor.lastrowid)
    
    def save_files_batch(self, files: List[FileInfo], batch_size: int = 1000, *,
                         volume_id: Optional[int] = None,
                         scan_id: Optional[int] = None) -> int:
        """Insert or refresh metadata for many files.

        Uses the same UPSERT contract as :meth:`save_file` (preserving extracted
        content, and preserving an existing non-NULL ``checksum``/``created_at``
        when the incoming scan value is NULL).

        Returns the number of **input records processed/upserted**, not the
        number of distinct database rows: if the same ``path`` appears twice in
        one input batch, both are processed and the count is 2 while the table
        keeps a single row.
        """
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
                        len(f.path.parts) - 1,
                        f.checksum or None,
                        volume_id,
                        scan_id,
                        "ACTIVE",
                        f.device_id,
                        f.inode,
                    )
                    for f in batch
                ]

                conn.executemany("""
                    INSERT INTO files (
                        path, filename, extension, size_bytes, file_type,
                        priority, created_at, modified_at, metadata,
                        parent_dir, depth, checksum,
                        volume_id, last_seen_scan_id, state, device_id, inode, indexed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(path) DO UPDATE SET
                        filename = excluded.filename,
                        extension = excluded.extension,
                        size_bytes = excluded.size_bytes,
                        file_type = excluded.file_type,
                        priority = excluded.priority,
                        created_at = COALESCE(excluded.created_at, files.created_at),
                        modified_at = excluded.modified_at,
                        metadata = excluded.metadata,
                        parent_dir = excluded.parent_dir,
                        depth = excluded.depth,
                        checksum = COALESCE(excluded.checksum, files.checksum),
                        volume_id = COALESCE(excluded.volume_id, files.volume_id),
                        last_seen_scan_id = COALESCE(excluded.last_seen_scan_id, files.last_seen_scan_id),
                        state = CASE WHEN excluded.last_seen_scan_id IS NOT NULL THEN 'ACTIVE' ELSE files.state END,
                        device_id = COALESCE(excluded.device_id, files.device_id),
                        inode = COALESCE(excluded.inode, files.inode),
                        indexed_at = CURRENT_TIMESTAMP
                """, data)

                total_saved += len(batch)

                if total_saved % 5000 == 0:
                    logger.info(f"Upserted {total_saved:,} files to database")

            conn.commit()

        logger.info(f"Total files upserted: {total_saved:,}")
        return total_saved
    
    def _build_filter_conditions(
        self,
        file_type: Optional[FileType],
        priority: Optional[Priority],
        extension: Optional[str],
        min_size: Optional[int],
        max_size: Optional[int],
    ) -> tuple[list[str], list[Any]]:
        """Build the SQL filter conditions shared by every search path."""
        conditions: list[str] = []
        params: list[Any] = []

        if file_type:
            conditions.append("file_type = ?")
            params.append(file_type.value if hasattr(file_type, "value") else str(file_type))
        if priority:
            conditions.append("priority = ?")
            params.append(priority.value if hasattr(priority, "value") else str(priority))
        if extension and extension.strip():
            conditions.append("extension = ?")
            params.append(extension.strip().lower())
        if min_size is not None:
            conditions.append("size_bytes >= ?")
            params.append(min_size)
        if max_size is not None:
            conditions.append("size_bytes <= ?")
            params.append(max_size)
        return conditions, params

    @staticmethod
    def _where(conditions: list[str]) -> str:
        return " AND ".join(conditions) if conditions else "1=1"

    def _search_files_fts(
        self,
        conn: sqlite3.Connection,
        query: str,
        conditions: list[str],
        params: list[Any],
        limit: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """FTS-backed lexical search; ``None`` when the query has no terms."""
        match_expression = build_fts_match(query)
        if match_expression is None:
            return None

        where = self._where(["files_fts MATCH ?", *conditions])
        sql = f"""
            SELECT files.* FROM files
            JOIN files_fts ON files_fts.rowid = files.id
            WHERE {where}
            ORDER BY bm25(files_fts), {_PRIORITY_RANK_SQL},
                     files.modified_at DESC, files.id ASC
            LIMIT ?
        """
        cursor = conn.execute(sql, [match_expression, *params, limit])
        return [dict(row) for row in cursor]

    def _search_files_like(
        self,
        conn: sqlite3.Connection,
        query: str,
        conditions: list[str],
        params: list[Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Legacy contiguous-substring fallback used when FTS is unusable."""
        like_term = f"%{query}%"
        where = self._where(
            [*conditions, "(filename LIKE ? OR path LIKE ? OR content_text LIKE ?)"]
        )
        sql = f"""
            SELECT * FROM files
            WHERE {where}
            ORDER BY {_PRIORITY_RANK_SQL}, modified_at DESC, id ASC
            LIMIT ?
        """
        cursor = conn.execute(sql, [*params, like_term, like_term, like_term, limit])
        return [dict(row) for row in cursor]

    def _search_files_all(
        self,
        conn: sqlite3.Connection,
        conditions: list[str],
        params: list[Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Filter-only search (no text query)."""
        sql = f"""
            SELECT * FROM files
            WHERE {self._where(conditions)}
            ORDER BY {_PRIORITY_RANK_SQL}, modified_at DESC, id ASC
            LIMIT ?
        """
        cursor = conn.execute(sql, [*params, limit])
        return [dict(row) for row in cursor]

    def search_files(
        self,
        query: Optional[str] = None,
        file_type: Optional[FileType] = None,
        priority: Optional[Priority] = None,
        extension: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        limit: int = 100,
        include_missing: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search files by lexical text plus metadata filters.

        Text queries use FTS5 with implicit AND between terms and support
        double-quoted exact phrases. Relevance (``bm25``) is the primary sort,
        followed by priority rank, modification time and id so ordering is
        deterministic. If the FTS query cannot be executed the method falls back
        to contiguous ``LIKE`` matching instead of raising.
        """
        conditions, params = self._build_filter_conditions(
            file_type, priority, extension, min_size, max_size
        )
        if not include_missing:
            conditions.append("COALESCE(files.state, 'ACTIVE') = 'ACTIVE'")

        with self.get_connection() as conn:
            if not (query and query.strip()):
                return self._search_files_all(conn, conditions, params, limit)

            try:
                results = self._search_files_fts(conn, query, conditions, params, limit)
                if results is not None:
                    return results
            except sqlite3.OperationalError as exc:
                logger.warning(f"FTS search failed, falling back to LIKE: {exc}")

            return self._search_files_like(conn, query, conditions, params, limit)
    
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
            
            # The AFTER UPDATE trigger keeps files_fts synchronised.
            conn.commit()
    
    def get_unprocessed_documents(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get documents that need content extraction."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM files
                WHERE content_extracted = 0
                AND file_type IN ('document', 'email')
                AND size_bytes < ?
                ORDER BY priority DESC, size_bytes ASC
                LIMIT ?
            """, (EXTRACTION_LIMIT, limit))
            
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