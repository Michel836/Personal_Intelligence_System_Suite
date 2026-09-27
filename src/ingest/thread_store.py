"""Conservative email thread relations (M017).

Thread membership is derived from RFC headers only (``Message-ID``,
``In-Reply-To``, ``References``). Subject text is **not** used to infer threads.
Relations are stored as evidence and can be surfaced by the M016 graph.
"""
from __future__ import annotations

import hashlib
from typing import Any


class EmailThreadStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._ensure()

    def _ensure(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_threads (
                    file_id INTEGER PRIMARY KEY,
                    message_id TEXT,
                    in_reply_to TEXT,
                    references_text TEXT,
                    subject TEXT,
                    date TEXT,
                    thread_key TEXT,
                    confidence TEXT DEFAULT 'HIGH',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_email_threads_msgid "
                         "ON email_threads(message_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_email_threads_key "
                         "ON email_threads(thread_key)")
            conn.commit()

    @staticmethod
    def _thread_key(message_id: str | None, references: str | None,
                    in_reply_to: str | None) -> str | None:
        root = None
        if references:
            first = references.split()[0].strip()
            root = first or None
        if not root:
            root = (in_reply_to or "").strip() or None
        if not root:
            root = (message_id or "").strip() or None
        if not root:
            return None
        return "thread:" + hashlib.sha1(root.encode("utf-8", "ignore")).hexdigest()[:16]

    def record(self, file_id: int, metadata: dict[str, Any]) -> None:
        message_id = metadata.get("message_id")
        in_reply_to = metadata.get("in_reply_to")
        references = metadata.get("references")
        thread_key = self._thread_key(message_id, references, in_reply_to)
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO email_threads
                       (file_id, message_id, in_reply_to, references_text, subject, date,
                        thread_key, confidence, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'HIGH', CURRENT_TIMESTAMP)
                   ON CONFLICT(file_id) DO UPDATE SET
                       message_id=excluded.message_id, in_reply_to=excluded.in_reply_to,
                       references_text=excluded.references_text, subject=excluded.subject,
                       date=excluded.date, thread_key=excluded.thread_key,
                       confidence='HIGH', updated_at=CURRENT_TIMESTAMP""",
                (int(file_id), message_id, in_reply_to, references, metadata.get("subject"),
                 metadata.get("date"), thread_key),
            )
            conn.commit()

    def clear(self, file_id: int) -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM email_threads WHERE file_id=?", (int(file_id),))
            conn.commit()

    def replies_for(self, file_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        """Documents that are replies to the same thread (header evidence only)."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT thread_key, in_reply_to, message_id FROM email_threads "
                               "WHERE file_id=?", (int(file_id),)).fetchone()
            if row is None:
                return []
            key = row["thread_key"]
            if not key:
                return []
            return [dict(r) for r in conn.execute(
                "SELECT t.file_id AS id, t.message_id, t.in_reply_to, t.subject, t.confidence, "
                "f.path, f.filename FROM email_threads t JOIN files f ON f.id=t.file_id "
                "WHERE t.thread_key=? AND t.file_id != ? AND COALESCE(f.state,'ACTIVE')='ACTIVE' LIMIT ?",
                (key, int(file_id), int(limit))).fetchall()]

    def stats(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM email_threads").fetchone()[0]
            threads = conn.execute("SELECT COUNT(DISTINCT thread_key) FROM email_threads "
                                   "WHERE thread_key IS NOT NULL").fetchone()[0]
        return {"messages": int(total), "threads": int(threads)}
