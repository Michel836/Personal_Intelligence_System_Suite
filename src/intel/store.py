"""Persistent M015 document-intelligence metadata (canonical SQLite).

Tables are additive and live beside ``files``: language, entities, categories,
PII findings, manual overrides, per-document processing state and a local audit
trail. Only masked PII displays and salted fingerprints are stored — never raw
sensitive values in logs or committed artifacts.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
from collections.abc import Iterable
from typing import Any

from loguru import logger

_INTEL_VERSION = "m015.1"


class IntelStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._ensure()

    # -- schema ------------------------------------------------------------
    def _ensure(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS doc_intel_state (
                    file_id INTEGER PRIMARY KEY,
                    source_indexed_at TEXT,
                    content_len INTEGER DEFAULT 0,
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS doc_language (
                    file_id INTEGER PRIMARY KEY,
                    lang TEXT NOT NULL,
                    confidence REAL DEFAULT 0,
                    method TEXT,
                    mixed TEXT,
                    version TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_language_lang ON doc_language(lang)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS doc_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    entity_type TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    display_value TEXT,
                    count INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 0,
                    method TEXT,
                    version TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (file_id, entity_type, normalized_value)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_entities_type ON doc_entities(entity_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_entities_norm ON doc_entities(entity_type, normalized_value)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_entities_file ON doc_entities(file_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS doc_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    score REAL DEFAULT 0,
                    source TEXT,
                    version TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (file_id, category)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_categories_cat ON doc_categories(category)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS category_overrides (
                    file_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    include INTEGER DEFAULT 1,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (file_id, category)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS doc_pii (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    pii_type TEXT NOT NULL,
                    severity TEXT DEFAULT 'medium',
                    count INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 0,
                    detector TEXT,
                    version TEXT,
                    fingerprint TEXT,
                    masked TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (file_id, pii_type, fingerprint)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_pii_type ON doc_pii(pii_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_pii_sev ON doc_pii(severity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_pii_file ON doc_pii(file_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS privacy_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id INTEGER,
                    detail TEXT,
                    sensitivity TEXT DEFAULT 'normal'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action)")
            conn.commit()

    # -- salt --------------------------------------------------------------
    def fingerprint_salt(self) -> str:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT value FROM privacy_meta WHERE key='pii_salt'").fetchone()
            if row:
                return str(row[0])
            salt = secrets.token_hex(16)
            conn.execute("INSERT OR REPLACE INTO privacy_meta(key, value) VALUES ('pii_salt', ?)", (salt,))
            conn.commit()
            return salt

    def fingerprint(self, value: str) -> str:
        salt = self.fingerprint_salt()
        return hashlib.blake2b((salt + "\x00" + value).encode("utf-8", "ignore"), digest_size=12).hexdigest()

    # -- state / freshness -------------------------------------------------
    def get_state(self, file_id: int) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM doc_intel_state WHERE file_id=?", (int(file_id),)).fetchone()
        return dict(row) if row else None

    def set_state(self, file_id: int, *, source_indexed_at: str | None, content_len: int) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO doc_intel_state(file_id, source_indexed_at, content_len, processed_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(file_id) DO UPDATE SET
                       source_indexed_at=excluded.source_indexed_at,
                       content_len=excluded.content_len,
                       processed_at=CURRENT_TIMESTAMP""",
                (int(file_id), source_indexed_at, int(content_len)),
            )
            conn.commit()

    def stale_documents(self, *, scope_prefix: str | None = None, min_chars: int = 1,
                        include_members: bool = False, limit: int | None = None,
                        force: bool = False) -> list[dict[str, Any]]:
        """Content-bearing docs whose intelligence is missing or out of date."""
        kinds = ["PHYSICAL_FILE", "ARCHIVE_MEMBER"] if include_members else ["PHYSICAL_FILE"]
        ph = ",".join("?" * len(kinds))
        sql = f"""
            SELECT f.id, f.path, f.content_text, f.indexed_at AS source_indexed_at,
                   length(f.content_text) AS content_len, f.document_kind
            FROM files f LEFT JOIN doc_intel_state s ON s.file_id = f.id
            WHERE f.document_kind IN ({ph})
              AND COALESCE(f.state,'ACTIVE')='ACTIVE'
              AND f.content_extracted=1 AND f.content_text IS NOT NULL
              AND length(f.content_text) >= ?
        """
        params: list[Any] = [*kinds, int(min_chars)]
        if not force:
            sql += (" AND (s.file_id IS NULL OR COALESCE(s.source_indexed_at,'') != COALESCE(f.indexed_at,'')"
                    " OR s.content_len != length(f.content_text))")
        if scope_prefix:
            escaped = scope_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND f.path LIKE ? ESCAPE '\\'"
            params.append(f"{escaped}%")
        sql += " ORDER BY f.id ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # -- per-document writes ----------------------------------------------
    def set_language(self, file_id: int, *, lang: str, confidence: float, method: str,
                     mixed: list[Any] | None = None) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO doc_language(file_id, lang, confidence, method, mixed, version, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(file_id) DO UPDATE SET
                       lang=excluded.lang, confidence=excluded.confidence, method=excluded.method,
                       mixed=excluded.mixed, version=excluded.version, updated_at=CURRENT_TIMESTAMP""",
                (int(file_id), lang, float(confidence), method,
                 json.dumps(mixed or [], ensure_ascii=False), _INTEL_VERSION),
            )
            conn.commit()

    def clear_document(self, file_id: int) -> None:
        with self.db.get_connection() as conn:
            for table in ("doc_language", "doc_entities", "doc_categories", "doc_pii"):
                conn.execute(f"DELETE FROM {table} WHERE file_id=?", (int(file_id),))
            conn.commit()

    def set_entities(self, file_id: int, entities: Iterable[dict[str, Any]]) -> None:
        rows = [(int(file_id), e["type"], e["normalized"], e.get("display"),
                 int(e.get("count", 1)), float(e.get("confidence", 0)), e.get("method"),
                 _INTEL_VERSION) for e in entities]
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM doc_entities WHERE file_id=?", (int(file_id),))
            conn.executemany(
                """INSERT OR REPLACE INTO doc_entities
                       (file_id, entity_type, normalized_value, display_value, count, confidence, method, version, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                rows,
            )
            conn.commit()

    def set_categories(self, file_id: int, categories: Iterable[dict[str, Any]]) -> None:
        rows = [(int(file_id), c["category"], float(c.get("score", 0)), c.get("source"), _INTEL_VERSION)
                for c in categories]
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM doc_categories WHERE file_id=?", (int(file_id),))
            conn.executemany(
                """INSERT OR REPLACE INTO doc_categories
                       (file_id, category, score, source, version, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                rows,
            )
            conn.commit()

    def set_pii(self, file_id: int, findings: Iterable[dict[str, Any]]) -> None:
        rows = [(int(file_id), p["type"], p.get("severity", "medium"), int(p.get("count", 1)),
                 float(p.get("confidence", 0)), p.get("detector"), _INTEL_VERSION,
                 p.get("fingerprint"), p.get("masked")) for p in findings]
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM doc_pii WHERE file_id=?", (int(file_id),))
            conn.executemany(
                """INSERT OR REPLACE INTO doc_pii
                       (file_id, pii_type, severity, count, confidence, detector, version, fingerprint, masked, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                rows,
            )
            conn.commit()

    # -- batched per-document write (one transaction per document/batch) ---
    def save_document_intel(self, file_id: int, *, language: dict[str, Any],
                            entities: Iterable[dict[str, Any]],
                            categories: Iterable[dict[str, Any]],
                            pii: Iterable[dict[str, Any]],
                            source_indexed_at: str | None, content_len: int) -> None:
        with self.db.get_connection() as conn:
            self.write_document_intel(conn, file_id, language=language, entities=entities,
                                      categories=categories, pii=pii,
                                      source_indexed_at=source_indexed_at, content_len=content_len)
            conn.commit()

    def write_document_intel(self, conn: Any, file_id: int, *, language: dict[str, Any],
                             entities: Iterable[dict[str, Any]],
                             categories: Iterable[dict[str, Any]],
                             pii: Iterable[dict[str, Any]],
                             source_indexed_at: str | None, content_len: int) -> None:
        """Write all intel for one document on an existing connection (no commit)."""
        fid = int(file_id)
        for table in ("doc_language", "doc_entities", "doc_categories", "doc_pii"):
            conn.execute(f"DELETE FROM {table} WHERE file_id=?", (fid,))
        conn.execute(
            """INSERT OR REPLACE INTO doc_language(file_id, lang, confidence, method, mixed, version, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (fid, language.get("lang", "und"), float(language.get("confidence", 0)),
             language.get("method"), json.dumps(language.get("mixed", []), ensure_ascii=False), _INTEL_VERSION),
        )
        conn.executemany(
            """INSERT OR REPLACE INTO doc_entities
                   (file_id, entity_type, normalized_value, display_value, count, confidence, method, version, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [(fid, e["type"], e["normalized"], e.get("display"), int(e.get("count", 1)),
              float(e.get("confidence", 0)), e.get("method"), _INTEL_VERSION) for e in entities],
        )
        conn.executemany(
            """INSERT OR REPLACE INTO doc_categories(file_id, category, score, source, version, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [(fid, c["category"], float(c.get("score", 0)), c.get("source"), _INTEL_VERSION)
             for c in categories],
        )
        conn.executemany(
            """INSERT OR REPLACE INTO doc_pii
                   (file_id, pii_type, severity, count, confidence, detector, version, fingerprint, masked, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [(fid, p["type"], p.get("severity", "medium"), int(p.get("count", 1)),
              float(p.get("confidence", 0)), p.get("detector"), _INTEL_VERSION,
              p.get("fingerprint"), p.get("masked")) for p in pii],
        )
        conn.execute(
            """INSERT INTO doc_intel_state(file_id, source_indexed_at, content_len, processed_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(file_id) DO UPDATE SET
                   source_indexed_at=excluded.source_indexed_at, content_len=excluded.content_len,
                   processed_at=CURRENT_TIMESTAMP""",
            (fid, source_indexed_at, int(content_len)),
        )

    # -- overrides ---------------------------------------------------------
    def set_override(self, file_id: int, category: str, *, include: bool = True) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO category_overrides(file_id, category, include, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (int(file_id), category, 1 if include else 0),
            )
            conn.commit()

    def overrides_for(self, file_id: int) -> dict[str, bool]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT category, include FROM category_overrides WHERE file_id=?", (int(file_id),)
            ).fetchall()
        return {r["category"]: bool(r["include"]) for r in rows}

    def all_overrides(self) -> dict[int, dict[str, bool]]:
        out: dict[int, dict[str, bool]] = {}
        with self.db.get_connection() as conn:
            for row in conn.execute("SELECT file_id, category, include FROM category_overrides"):
                out.setdefault(int(row["file_id"]), {})[row["category"]] = bool(row["include"])
        return out

    # -- reads -------------------------------------------------------------
    def get_language(self, file_id: int) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM doc_language WHERE file_id=?", (int(file_id),)).fetchone()
        return dict(row) if row else None

    def get_entities(self, file_id: int) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM doc_entities WHERE file_id=? ORDER BY entity_type, count DESC",
                (int(file_id),)).fetchall()]

    def get_categories(self, file_id: int) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM doc_categories WHERE file_id=? ORDER BY score DESC",
                (int(file_id),)).fetchall()]

    def get_pii(self, file_id: int) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM doc_pii WHERE file_id=? ORDER BY severity DESC, count DESC",
                (int(file_id),)).fetchall()]

    def max_severity(self, file_id: int) -> str | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT severity FROM doc_pii WHERE file_id=? ORDER BY "
                               "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END LIMIT 1",
                               (int(file_id),)).fetchone()
        return row[0] if row else None

    # -- pruning -----------------------------------------------------------
    def prune_removed(self) -> dict[str, int]:
        active = "SELECT id FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'"
        counts = {}
        with self.db.get_connection() as conn:
            for table in ("doc_intel_state", "doc_language", "doc_entities", "doc_categories", "doc_pii"):
                counts[table] = int(conn.execute(
                    f"DELETE FROM {table} WHERE file_id NOT IN ({active})").rowcount or 0)
            conn.commit()
        return counts

    # -- aggregate stats ---------------------------------------------------
    def stats(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            lang = dict(conn.execute("SELECT lang, COUNT(*) FROM doc_language GROUP BY lang ORDER BY 2 DESC").fetchall())
            cats = dict(conn.execute("SELECT category, COUNT(*) FROM doc_categories GROUP BY category ORDER BY 2 DESC").fetchall())
            pii = dict(conn.execute("SELECT pii_type, COUNT(*) FROM doc_pii GROUP BY pii_type ORDER BY 2 DESC").fetchall())
            sev = dict(conn.execute("SELECT severity, COUNT(*) FROM doc_pii GROUP BY severity").fetchall())
            ent = dict(conn.execute("SELECT entity_type, COUNT(*) FROM doc_entities GROUP BY entity_type ORDER BY 2 DESC").fetchall())
            docs = conn.execute("SELECT COUNT(*) FROM doc_language").fetchone()[0]
        return {"documents": int(docs), "languages": lang, "categories": cats,
                "pii_types": pii, "pii_severity": sev, "entity_types": ent}

    def entity_documents(self, entity_type: str, normalized_value: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT e.file_id AS id, e.count, e.confidence, f.path, f.filename,
                          COALESCE(f.state,'ACTIVE') AS state
                   FROM doc_entities e JOIN files f ON f.id=e.file_id
                   WHERE e.entity_type=? AND e.normalized_value=?
                     AND COALESCE(f.state,'ACTIVE')='ACTIVE'
                   ORDER BY e.count DESC LIMIT ?""",
                (entity_type, normalized_value, int(limit))).fetchall()]

    # -- audit -------------------------------------------------------------
    def record_audit(self, action: str, *, target_type: str | None = None,
                     target_id: int | None = None, detail: str | None = None,
                     sensitivity: str = "normal") -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO audit_events(action, target_type, target_id, detail, sensitivity)
                   VALUES (?, ?, ?, ?, ?)""",
                (action, target_type, target_id, detail, sensitivity),
            )
            conn.commit()
        with contextlib.suppress(Exception):  # audit must never break the caller
            logger.bind(audit=True).info(
                f"audit action={action} target={target_type}:{target_id} sensitivity={sensitivity}"
            )

    def audit_events(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]

    def prune_audit(self, keep: int = 10000) -> int:
        with self.db.get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM audit_events WHERE id NOT IN "
                "(SELECT id FROM audit_events ORDER BY id DESC LIMIT ?)", (int(keep),))
            conn.commit()
            return int(cur.rowcount or 0)
