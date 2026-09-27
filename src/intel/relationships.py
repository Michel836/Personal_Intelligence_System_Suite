"""Derived entity/relationship views (M015).

These surface *co-occurrence and filtering views only*. They never infer human
or organisational relationships from co-occurrence: sharing an entity means the
entity occurs in both documents, nothing more.
"""
from __future__ import annotations

from typing import Any, cast


def entity_frequency(store: Any, *, entity_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = ("SELECT entity_type, normalized_value, display_value, COUNT(DISTINCT file_id) AS docs, "
           "SUM(count) AS mentions FROM doc_entities")
    params: list[Any] = []
    if entity_type:
        sql += " WHERE entity_type = ?"
        params.append(entity_type)
    sql += " GROUP BY entity_type, normalized_value ORDER BY docs DESC, mentions DESC LIMIT ?"
    params.append(int(limit))
    with store.db.get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def documents_sharing_entity(store: Any, entity_type: str, normalized_value: str, *, limit: int = 100) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", store.entity_documents(entity_type, normalized_value, limit=limit))


def documents_by_language(store: Any, lang: str, *, limit: int = 100) -> list[dict[str, Any]]:
    with store.db.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT f.id, f.path, f.filename, dl.confidence, dl.lang
               FROM doc_language dl JOIN files f ON f.id=dl.file_id
               WHERE dl.lang=? AND COALESCE(f.state,'ACTIVE')='ACTIVE' LIMIT ?""",
            (lang, int(limit))).fetchall()]


def documents_by_category(store: Any, category: str, *, limit: int = 100) -> list[dict[str, Any]]:
    with store.db.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT f.id, f.path, f.filename, dc.score, dc.source
               FROM doc_categories dc JOIN files f ON f.id=dc.file_id
               WHERE dc.category=? AND COALESCE(f.state,'ACTIVE')='ACTIVE'
               ORDER BY dc.score DESC LIMIT ?""",
            (category, int(limit))).fetchall()]
