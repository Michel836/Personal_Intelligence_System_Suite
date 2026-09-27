"""Provenance-aware document timeline (M016).

Every timeline item carries its **date source** and confidence; the engine never
collapses filesystem, creation, indexing and document dates into one ambiguous
timestamp, and never invents chronology when evidence is missing.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .relations import _like_prefix

#: date_source -> (confidence, human meaning)
DATE_SOURCES = {
    "modified_at": ("HIGH", "filesystem modification time"),
    "created_at": ("MEDIUM", "filesystem creation time (when provided by the OS)"),
    "indexed_at": ("LOW", "time the application indexed the document (not a document date)"),
    "version_date": ("MEDIUM", "explicit date parsed from the file name"),
}


@dataclass
class TimelineEvent:
    file_id: int
    date: str
    date_source: str
    confidence: str
    filename: str | None = None
    extension: str | None = None
    document_kind: str | None = None
    state: str = "ACTIVE"
    language: str | None = None
    provenance: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"file_id": self.file_id, "date": self.date, "date_source": self.date_source,
                "confidence": self.confidence, "filename": self.filename,
                "extension": self.extension, "document_kind": self.document_kind,
                "state": self.state, "language": self.language, "provenance": self.provenance}


def _bucket_key(iso_date: str, group: str) -> str:
    if group == "day":
        return iso_date[:10]
    if group == "month":
        return iso_date[:7]
    if group == "year":
        return iso_date[:4]
    if group == "week":
        try:
            y, m, d = (int(x) for x in iso_date[:10].split("-"))
            wk = date(y, m, d).isocalendar()
            return f"{wk[0]}-W{wk[1]:02d}"
        except Exception:
            return iso_date[:10]
    return iso_date[:10]


class TimelineService:
    def __init__(self, db: Any, *, intel_store: Any = None) -> None:
        self.db = db
        self._intel = intel_store
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        with self.db.get_connection() as conn:
            for name, col in (("idx_files_indexed_at", "indexed_at"), ("idx_files_created_at", "created_at")):
                with contextlib.suppress(Exception):  # column may be absent on very old DBs
                    conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON files({col})")
            conn.commit()

    def intel(self) -> Any:
        if self._intel is None:
            from ..intel import IntelStore
            self._intel = IntelStore(self.db)
        return self._intel

    # -- query -------------------------------------------------------------
    def events(self, *, start: str | None = None, end: str | None = None,
               source: str = "modified_at", group: str = "month",
               scope_prefix: str | None = None, language: str | None = None,
               category: str | None = None, entity_type: str | None = None,
               entity_value: str | None = None, has_pii: bool | None = None,
               exclude_high_sensitivity: bool = False, extension: str | None = None,
               document_kind: str | None = None, include_missing: bool = False,
               limit: int = 5000) -> dict[str, Any]:
        if source not in DATE_SOURCES:
            source = "modified_at"
        conditions = ["1=1"]
        params: list[Any] = []
        if source != "version_date":
            conditions.append(f"files.{source} IS NOT NULL")
            if start:
                conditions.append(f"files.{source} >= ?")
                params.append(start)
            if end:
                conditions.append(f"files.{source} <= ?")
                params.append(end)
        if scope_prefix:
            conditions.append("files.path LIKE ? ESCAPE '\\'")
            params.append(_like_prefix(scope_prefix))
        if language:
            conditions.append("files.id IN (SELECT file_id FROM doc_language WHERE lang=?)")
            params.append(language)
        if category:
            conditions.append("files.id IN (SELECT file_id FROM doc_categories WHERE category=?)")
            params.append(category)
        if entity_type and entity_value is not None:
            conditions.append("files.id IN (SELECT file_id FROM doc_entities "
                              "WHERE entity_type=? AND normalized_value=?)")
            params.extend([entity_type, entity_value])
        elif entity_type:
            conditions.append("files.id IN (SELECT file_id FROM doc_entities WHERE entity_type=?)")
            params.append(entity_type)
        if has_pii is True:
            conditions.append("files.id IN (SELECT file_id FROM doc_pii)")
        elif has_pii is False:
            conditions.append("files.id NOT IN (SELECT file_id FROM doc_pii)")
        if exclude_high_sensitivity:
            conditions.append("files.id NOT IN (SELECT file_id FROM doc_pii WHERE severity='high')")
        if extension:
            conditions.append("files.extension = ?")
            params.append(extension.lower())
        if document_kind:
            conditions.append("COALESCE(files.document_kind,'PHYSICAL_FILE') = ?")
            params.append(document_kind)
        if not include_missing:
            conditions.append("COALESCE(files.state,'ACTIVE')='ACTIVE'")

        order_col = "files.modified_at" if source == "version_date" else f"files.{source}"
        sql = (f"SELECT files.id, files.filename, files.extension, files.document_kind, "
               f"COALESCE(files.state,'ACTIVE') AS state, files.modified_at, files.created_at, "
               f"files.indexed_at FROM files WHERE {' AND '.join(conditions)} "
               f"ORDER BY {order_col} DESC, files.id ASC LIMIT ?")
        params.append(int(limit))
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        lang_by_id = self._languages([int(r["id"]) for r in rows]) if rows else {}
        events: list[TimelineEvent] = []
        buckets: dict[str, int] = {}
        source_used: dict[str, int] = {}
        for r in rows:
            iso = self._resolve_date(r, source)
            if iso is None:
                continue
            sid = int(r["id"])
            conf, meaning = DATE_SOURCES[iso[1]]
            ev = TimelineEvent(sid, iso[0], iso[1], conf, r.get("filename"), r.get("extension"),
                               r.get("document_kind"), r.get("state", "ACTIVE"),
                               lang_by_id.get(sid), meaning)
            events.append(ev)
            buckets[_bucket_key(iso[0], group)] = buckets.get(_bucket_key(iso[0], group), 0) + 1
            source_used[iso[1]] = source_used.get(iso[1], 0) + 1
        return {"events": [e.as_dict() for e in events],
                "buckets": [{"bucket": k, "count": v} for k, v in sorted(buckets.items())],
                "sources": source_used, "date_source": source,
                "confidence": DATE_SOURCES[source][0], "group": group,
                "count": len(events), "provenance": DATE_SOURCES[source][1]}

    def _languages(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        out: dict[int, str] = {}
        try:
            with self.db.get_connection() as conn:
                for i in range(0, len(ids), 900):
                    chunk = ids[i:i + 900]
                    ph = ",".join("?" * len(chunk))
                    for fid, lang in conn.execute(
                            f"SELECT file_id, lang FROM doc_language WHERE file_id IN ({ph})", chunk):
                        out[int(fid)] = lang
        except Exception:  # noqa: BLE001 - M015 tables may be absent
            return {}
        return out

    @staticmethod
    def _resolve_date(row: dict[str, Any], source: str) -> tuple[str, str] | None:
        if source == "version_date":
            from ..dedup.versions import version_marker
            mk = version_marker(row.get("filename") or "")
            if mk and mk.get("kind") == "date":
                return (mk["value"][:10], "version_date")
            return None
        value = row.get(source)
        if not value:
            return None
        text = str(value)
        try:
            iso = datetime.fromisoformat(text.replace("Z", "")).date().isoformat()
        except ValueError:
            iso = text[:10]
        return (iso, source)

    def sources_summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        with self.db.get_connection() as conn:
            for src in ("modified_at", "created_at", "indexed_at"):
                try:
                    n = conn.execute(
                        f"SELECT COUNT(*) FROM files WHERE {src} IS NOT NULL").fetchone()[0]
                except Exception:
                    n = 0
                out[src] = {"available": int(n), "confidence": DATE_SOURCES[src][0]}
        out["version_date"] = {"available": None, "confidence": DATE_SOURCES["version_date"][0],
                               "note": "parsed on demand from file names"}
        return out
