"""Persistent local extraction error / retry queue (M017).

Stores only non-sensitive metadata (file id, operation, outcome, short detail
code, attempts, timestamps). Never stores extracted content, email addresses or
secrets; raw values must be redacted by the caller before recording.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .taxonomy import (
    MAX_ATTEMPTS,
    RETRYABLE,
    Outcome,
    backoff_seconds,
    is_retryable,
    is_terminal,
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


class ExtractionQueue:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._ensure()

    def _ensure(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extraction_queue (
                    file_id INTEGER NOT NULL,
                    operation TEXT NOT NULL DEFAULT 'extract',
                    outcome TEXT NOT NULL,
                    detail TEXT,
                    attempts INTEGER NOT NULL DEFAULT 1,
                    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_attempted TEXT DEFAULT CURRENT_TIMESTAMP,
                    retry_after TEXT,
                    terminal INTEGER NOT NULL DEFAULT 0,
                    ignored INTEGER NOT NULL DEFAULT 0,
                    extractor_version TEXT,
                    PRIMARY KEY (file_id, operation)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extraction_queue_outcome "
                         "ON extraction_queue(outcome)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extraction_queue_retry "
                         "ON extraction_queue(terminal, retry_after)")
            conn.commit()

    def record(self, file_id: int, outcome: str, *, detail: str | None = None,
               operation: str = "extract", extractor_version: str = "m017.1") -> dict[str, Any]:
        fid = int(file_id)
        safe_detail = (detail or "")[:160]
        now = _now_iso()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT attempts FROM extraction_queue WHERE file_id=? AND operation=?",
                (fid, operation)).fetchone()
            attempts = (int(row["attempts"]) + 1) if row else 1
            terminal = 1 if is_terminal(outcome) or outcome == Outcome.EXTRACTED.value else 0
            retry_after = None
            if not terminal and is_retryable(outcome, attempts=attempts):
                retry_after = (datetime.now(UTC).replace(tzinfo=None)
                               + timedelta(seconds=backoff_seconds(attempts))).isoformat(sep=" ", timespec="seconds")
            elif not terminal and attempts >= MAX_ATTEMPTS:
                terminal = 1  # exhausted retries
            conn.execute(
                """INSERT INTO extraction_queue
                       (file_id, operation, outcome, detail, attempts, first_seen, last_attempted,
                        retry_after, terminal, ignored, extractor_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(file_id, operation) DO UPDATE SET
                       outcome=excluded.outcome, detail=excluded.detail, attempts=excluded.attempts,
                       last_attempted=excluded.last_attempted, retry_after=excluded.retry_after,
                       terminal=excluded.terminal, ignored=0,
                       extractor_version=excluded.extractor_version""",
                (fid, operation, outcome, safe_detail, attempts, now, now, retry_after,
                 terminal, extractor_version),
            )
            conn.commit()
        return {"file_id": fid, "outcome": outcome, "attempts": attempts,
                "terminal": bool(terminal), "retry_after": retry_after}

    def clear(self, file_id: int, *, operation: str = "extract") -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM extraction_queue WHERE file_id=? AND operation=?",
                         (int(file_id), operation))
            conn.commit()

    def ignore(self, file_id: int, *, operation: str = "extract") -> None:
        with self.db.get_connection() as conn:
            conn.execute("UPDATE extraction_queue SET ignored=1, terminal=1 "
                         "WHERE file_id=? AND operation=?", (int(file_id), operation))
            conn.commit()

    def retryable(self, *, limit: int = 200, now: str | None = None) -> list[dict[str, Any]]:
        """Rows eligible for an automatic bounded retry.

        Only the documented retryable outcomes are returned: a non-terminal but
        non-retryable outcome (``OCR_REQUIRED``, blocked on opt-in) must be
        retried explicitly, not swept up here indefinitely.
        """
        now = now or _now_iso()
        outcomes = sorted(RETRYABLE)
        placeholders = ",".join("?" * len(outcomes))
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                f"""SELECT q.*, q.file_id AS id, f.path, f.filename, f.extension,
                           COALESCE(f.state,'ACTIVE') AS state
                    FROM extraction_queue q JOIN files f ON f.id=q.file_id
                    WHERE q.terminal=0 AND q.ignored=0
                      AND q.outcome IN ({placeholders})
                      AND (q.retry_after IS NULL OR q.retry_after <= ?)
                      AND COALESCE(f.state,'ACTIVE')='ACTIVE'
                    ORDER BY q.attempts ASC, q.last_attempted ASC LIMIT ?""",
                (*outcomes, now, int(limit))).fetchall()]

    def issues(self, *, limit: int = 500, include_ignored: bool = False) -> list[dict[str, Any]]:
        clause = "" if include_ignored else "AND q.ignored=0"
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                f"""SELECT q.*, q.file_id AS id, f.path, f.filename, f.extension,
                           COALESCE(f.state,'ACTIVE') AS state
                    FROM extraction_queue q JOIN files f ON f.id=q.file_id
                    WHERE q.outcome != 'EXTRACTED' {clause}
                    ORDER BY q.last_attempted DESC LIMIT ?""", (int(limit),)).fetchall()]

    def stats(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            by_outcome = dict(conn.execute(
                "SELECT outcome, COUNT(*) FROM extraction_queue GROUP BY outcome ORDER BY 2 DESC").fetchall())
            pending = conn.execute(
                "SELECT COUNT(*) FROM extraction_queue WHERE terminal=0 AND ignored=0").fetchone()[0]
        return {"by_outcome": by_outcome, "retryable_pending": int(pending),
                "total": int(sum(by_outcome.values()))}

    def prune_missing(self) -> int:
        active = "SELECT id FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'"
        with self.db.get_connection() as conn:
            cur = conn.execute(f"DELETE FROM extraction_queue WHERE file_id NOT IN ({active})")
            conn.commit()
            return int(cur.rowcount or 0)
