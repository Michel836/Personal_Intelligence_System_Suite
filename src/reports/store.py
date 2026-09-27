"""Persistence for report definitions, artifacts, dossiers and saved queries.

Additive-only tables in the **canonical** SQLite database. No parallel document
store is created: dossiers reference ``files.id`` and reports reference their
definition; document content lives only in the existing ``files`` table.

Artifact rows store paths + checksums, never document content, so the database
does not duplicate what the filesystem already holds.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import DossierMode, ReportArtifact, ReportDefinition


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


class ReportStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._ensure()

    def _ensure(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS report_definitions (
                    report_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    query_json TEXT,
                    document_ids_json TEXT,
                    privacy_mode TEXT NOT NULL DEFAULT 'FULL_LOCAL',
                    options_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS report_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT NOT NULL,
                    format TEXT NOT NULL,
                    path TEXT NOT NULL,
                    checksum TEXT,
                    size_bytes INTEGER,
                    generator_version TEXT,
                    provider TEXT,
                    privacy_mode TEXT,
                    warnings_json TEXT,
                    logical_fingerprint TEXT,
                    generated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_report_artifacts_report "
                         "ON report_artifacts(report_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dossiers (
                    dossier_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    mode TEXT NOT NULL DEFAULT 'STATIC',
                    query_json TEXT,
                    frozen_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dossier_documents (
                    dossier_id TEXT NOT NULL,
                    file_id INTEGER NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    section TEXT,
                    note TEXT,
                    manual INTEGER NOT NULL DEFAULT 1,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (dossier_id, file_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dossier_sections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dossier_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS saved_queries (
                    query_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    query_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # -- report definitions -------------------------------------------------
    def save_definition(self, definition: ReportDefinition) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO report_definitions
                       (report_id, kind, title, description, query_json, document_ids_json,
                        privacy_mode, options_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(report_id) DO UPDATE SET
                       kind=excluded.kind, title=excluded.title, description=excluded.description,
                       query_json=excluded.query_json, document_ids_json=excluded.document_ids_json,
                       privacy_mode=excluded.privacy_mode, options_json=excluded.options_json,
                       updated_at=excluded.updated_at""",
                (definition.report_id, definition.kind, definition.title, definition.description,
                 json.dumps(definition.query), json.dumps(definition.document_ids),
                 definition.privacy_mode, json.dumps(definition.options),
                 definition.created_at, _now_iso()),
            )
            conn.commit()

    def get_definition(self, report_id: str) -> ReportDefinition | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM report_definitions WHERE report_id=?",
                               (report_id,)).fetchone()
        if row is None:
            return None
        return self._definition_from_row(dict(row))

    def list_definitions(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM report_definitions ORDER BY COALESCE(updated_at, created_at) DESC "
                "LIMIT ?", (int(limit),)).fetchall()]
        return [{**r, "definition": self._definition_from_row(r).as_dict()} for r in rows]

    @staticmethod
    def _definition_from_row(row: dict[str, Any]) -> ReportDefinition:
        return ReportDefinition.from_dict({
            "report_id": row["report_id"], "kind": row["kind"], "title": row["title"],
            "description": row.get("description") or "",
            "created_at": row.get("created_at") or _now_iso(),
            "query": json.loads(row.get("query_json") or "{}"),
            "document_ids": json.loads(row.get("document_ids_json") or "[]"),
            "privacy_mode": row.get("privacy_mode") or "FULL_LOCAL",
            "options": json.loads(row.get("options_json") or "{}"),
        })

    # -- artifacts ----------------------------------------------------------
    def record_artifact(self, artifact: ReportArtifact) -> int:
        with self.db.get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO report_artifacts
                       (report_id, format, path, checksum, size_bytes, generator_version,
                        provider, privacy_mode, warnings_json, logical_fingerprint, generated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (artifact.report_id, artifact.format, artifact.path, artifact.checksum,
                 int(artifact.size_bytes), artifact.generator_version, artifact.provider,
                 artifact.privacy_mode, json.dumps(artifact.warnings),
                 artifact.logical_fingerprint, artifact.generated_at),
            )
            conn.commit()
            return int(cur.lastrowid or 0)

    def artifacts_for(self, report_id: str) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM report_artifacts WHERE report_id=? ORDER BY generated_at DESC",
                (report_id,)).fetchall()]
        for r in rows:
            r["exists"] = Path(r["path"]).is_file() if r.get("path") else False
            r["warnings"] = json.loads(r.get("warnings_json") or "[]")
        return rows

    def list_artifacts(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT a.*, d.title FROM report_artifacts a "
                "LEFT JOIN report_definitions d ON d.report_id=a.report_id "
                "ORDER BY a.generated_at DESC LIMIT ?", (int(limit),)).fetchall()]
        for r in rows:
            r["exists"] = Path(r["path"]).is_file() if r.get("path") else False
            r["warnings"] = json.loads(r.get("warnings_json") or "[]")
        return rows

    def prune_missing_artifacts(self) -> int:
        with self.db.get_connection() as conn:
            rows = [r["id"] for r in conn.execute(
                "SELECT id, path FROM report_artifacts").fetchall()
                if r["path"] and not Path(r["path"]).is_file()]
            for rid in rows:
                conn.execute("DELETE FROM report_artifacts WHERE id=?", (int(rid),))
            conn.commit()
        return len(rows)

    # -- dossiers -----------------------------------------------------------
    def create_dossier(self, dossier_id: str, name: str, *, description: str = "",
                       mode: str = DossierMode.STATIC.value,
                       query: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now_iso()
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO dossiers (dossier_id, name, description, mode, query_json,
                                         created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (dossier_id, name, description, mode, json.dumps(query or {}), now, now),
            )
            conn.commit()
        return self.get_dossier(dossier_id) or {}

    def get_dossier(self, dossier_id: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM dossiers WHERE dossier_id=?",
                               (dossier_id,)).fetchone()
            if row is None:
                return None
            members = [dict(r) for r in conn.execute(
                "SELECT * FROM dossier_documents WHERE dossier_id=? ORDER BY position ASC, added_at ASC",
                (dossier_id,)).fetchall()]
            sections = [dict(r) for r in conn.execute(
                "SELECT * FROM dossier_sections WHERE dossier_id=? ORDER BY position ASC, id ASC",
                (dossier_id,)).fetchall()]
        out = dict(row)
        out["query"] = json.loads(out.pop("query_json") or "{}")
        out["frozen"] = json.loads(out.pop("frozen_json") or "null")
        out["members"] = members
        out["sections"] = sections
        return out

    def list_dossiers(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT dossier_id, name, description, mode, query_json, created_at, updated_at "
                "FROM dossiers ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?",
                (int(limit),)).fetchall()]
            for r in rows:
                r["query"] = json.loads(r.pop("query_json") or "{}")
                r["member_count"] = int(conn.execute(
                    "SELECT COUNT(*) FROM dossier_documents WHERE dossier_id=?",
                    (r["dossier_id"],)).fetchone()[0])
        return rows

    def rename_dossier(self, dossier_id: str, name: str, *, description: str | None = None) -> None:
        with self.db.get_connection() as conn:
            if description is None:
                conn.execute("UPDATE dossiers SET name=?, updated_at=? WHERE dossier_id=?",
                             (name, _now_iso(), dossier_id))
            else:
                conn.execute("UPDATE dossiers SET name=?, description=?, updated_at=? WHERE dossier_id=?",
                             (name, description, _now_iso(), dossier_id))
            conn.commit()

    def delete_dossier(self, dossier_id: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM dossier_documents WHERE dossier_id=?", (dossier_id,))
            conn.execute("DELETE FROM dossier_sections WHERE dossier_id=?", (dossier_id,))
            conn.execute("DELETE FROM dossiers WHERE dossier_id=?", (dossier_id,))
            conn.commit()

    def set_dossier_mode(self, dossier_id: str, mode: str,
                         query: dict[str, Any] | None = None) -> None:
        with self.db.get_connection() as conn:
            if query is None:
                conn.execute("UPDATE dossiers SET mode=?, updated_at=? WHERE dossier_id=?",
                             (mode, _now_iso(), dossier_id))
            else:
                conn.execute(
                    "UPDATE dossiers SET mode=?, query_json=?, updated_at=? WHERE dossier_id=?",
                    (mode, json.dumps(query), _now_iso(), dossier_id))
            conn.commit()

    def add_documents(self, dossier_id: str, file_ids: list[int], *,
                      section: str | None = None, note: str | None = None,
                      manual: bool = True) -> int:
        if not file_ids:
            return 0
        now = _now_iso()
        with self.db.get_connection() as conn:
            base = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM dossier_documents "
                                "WHERE dossier_id=?", (dossier_id,)).fetchone()[0]
            added = 0
            for offset, fid in enumerate(file_ids):
                cur = conn.execute(
                    """INSERT INTO dossier_documents
                           (dossier_id, file_id, position, section, note, manual, added_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(dossier_id, file_id) DO UPDATE SET
                           section=COALESCE(excluded.section, dossier_documents.section),
                           note=COALESCE(excluded.note, dossier_documents.note),
                           manual=MAX(dossier_documents.manual, excluded.manual)""",
                    (dossier_id, int(fid), int(base) + offset, section, note,
                     1 if manual else 0, now),
                )
                added += 1 if cur.rowcount else 0
            conn.execute("UPDATE dossiers SET updated_at=? WHERE dossier_id=?", (now, dossier_id))
            conn.commit()
        return added

    def remove_documents(self, dossier_id: str, file_ids: list[int]) -> int:
        if not file_ids:
            return 0
        with self.db.get_connection() as conn:
            removed = 0
            for fid in file_ids:
                cur = conn.execute("DELETE FROM dossier_documents WHERE dossier_id=? AND file_id=?",
                                   (dossier_id, int(fid)))
                removed += 1 if cur.rowcount else 0
            conn.execute("UPDATE dossiers SET updated_at=? WHERE dossier_id=?",
                         (_now_iso(), dossier_id))
            conn.commit()
        return removed

    def reorder_documents(self, dossier_id: str, ordered_ids: list[int]) -> None:
        with self.db.get_connection() as conn:
            for position, fid in enumerate(ordered_ids):
                conn.execute("UPDATE dossier_documents SET position=? WHERE dossier_id=? AND file_id=?",
                             (position, dossier_id, int(fid)))
            conn.execute("UPDATE dossiers SET updated_at=? WHERE dossier_id=?",
                         (_now_iso(), dossier_id))
            conn.commit()

    def set_member_note(self, dossier_id: str, file_id: int, note: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute("UPDATE dossier_documents SET note=? WHERE dossier_id=? AND file_id=?",
                         (note, dossier_id, int(file_id)))
            conn.commit()

    def add_section(self, dossier_id: str, title: str) -> int:
        with self.db.get_connection() as conn:
            pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM dossier_sections "
                               "WHERE dossier_id=?", (dossier_id,)).fetchone()[0]
            cur = conn.execute("INSERT INTO dossier_sections (dossier_id, title, position) "
                               "VALUES (?, ?, ?)", (dossier_id, title, int(pos)))
            conn.commit()
            return int(cur.lastrowid or 0)

    def remove_section(self, dossier_id: str, section_id: int) -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM dossier_sections WHERE dossier_id=? AND id=?",
                         (dossier_id, int(section_id)))
            conn.commit()

    def freeze(self, dossier_id: str, member_ids: list[int], *,
               fingerprint: str | None = None) -> None:
        payload = {"ids": [int(i) for i in member_ids], "at": _now_iso(),
                   "fingerprint": fingerprint}
        with self.db.get_connection() as conn:
            conn.execute("UPDATE dossiers SET frozen_json=?, updated_at=? WHERE dossier_id=?",
                         (json.dumps(payload), _now_iso(), dossier_id))
            conn.commit()

    def unfreeze(self, dossier_id: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute("UPDATE dossiers SET frozen_json=NULL, updated_at=? WHERE dossier_id=?",
                         (_now_iso(), dossier_id))
            conn.commit()

    # -- saved queries ------------------------------------------------------
    def save_query(self, query_id: str, name: str, query: dict[str, Any]) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO saved_queries (query_id, name, query_json, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(query_id) DO UPDATE SET name=excluded.name,
                       query_json=excluded.query_json""",
                (query_id, name, json.dumps(query), _now_iso()))
            conn.commit()

    def list_saved_queries(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM saved_queries ORDER BY created_at DESC LIMIT ?",
                (int(limit),)).fetchall()]
        for r in rows:
            r["query"] = json.loads(r.pop("query_json") or "{}")
        return rows

    def get_saved_query(self, query_id: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM saved_queries WHERE query_id=?",
                               (query_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["query"] = json.loads(out.pop("query_json") or "{}")
        return out

    def delete_saved_query(self, query_id: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM saved_queries WHERE query_id=?", (query_id,))
            conn.commit()
