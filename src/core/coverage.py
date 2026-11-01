"""Lightweight corpus coverage metrics (no heavy imports).

Used by ``pis status``, the doctor, the sidebar and the embedding job. Keeping
this module dependency-free avoids importing the AI stack just to display a
percentage.
"""
from __future__ import annotations

from typing import Any


def _min_content(db: Any) -> int:
    return int(getattr(db, "SEMANTIC_MIN_CONTENT", 50) or 50)


def semantic_coverage(db: Any) -> dict[str, Any]:
    """Return corpus-level semantic coverage (aggregate only, no content)."""
    threshold = _min_content(db)
    with db.get_connection() as conn:
        eligible = int(conn.execute(
            "SELECT COUNT(*) FROM files WHERE content_extracted = 1 "
            "AND content_text IS NOT NULL AND length(content_text) > ? "
            "AND COALESCE(state, 'ACTIVE') = 'ACTIVE'",
            (threshold,),
        ).fetchone()[0])
        embedded = int(conn.execute(
            "SELECT COUNT(*) FROM semantic_state s JOIN files f ON f.id = s.file_id "
            "WHERE s.embedded_version IS NOT NULL AND s.prune = 0 "
            "AND COALESCE(f.state, 'ACTIVE') = 'ACTIVE' "
            "AND f.content_extracted = 1 AND f.content_text IS NOT NULL "
            "AND length(f.content_text) > ?",
            (threshold,),
        ).fetchone()[0])
        dirty = int(conn.execute(
            "SELECT COUNT(*) FROM semantic_state s JOIN files f ON f.id = s.file_id "
            "WHERE s.dirty = 1 AND s.prune = 0 "
            "AND COALESCE(f.state, 'ACTIVE') = 'ACTIVE' "
            "AND f.content_extracted = 1 AND f.content_text IS NOT NULL "
            "AND length(f.content_text) > ?",
            (threshold,),
        ).fetchone()[0])
    pending = max(0, eligible - embedded)
    percent = round(100.0 * embedded / eligible, 1) if eligible else 0.0
    return {
        "eligible": eligible,
        "embedded": embedded,
        "pending": pending,
        "dirty": dirty,
        "percent": percent,
    }


def extraction_coverage(db: Any) -> dict[str, Any]:
    """Return how much of the indexed corpus has extracted content."""
    with db.get_connection() as conn:
        active = int(conn.execute(
            "SELECT COUNT(*) FROM files WHERE COALESCE(state, 'ACTIVE') = 'ACTIVE'"
        ).fetchone()[0])
        extracted = int(conn.execute(
            "SELECT COUNT(*) FROM files WHERE content_extracted = 1 "
            "AND content_text IS NOT NULL AND length(content_text) > 0 "
            "AND COALESCE(state, 'ACTIVE') = 'ACTIVE'"
        ).fetchone()[0])
    percent = round(100.0 * extracted / active, 1) if active else 0.0
    return {"active_files": active, "extracted": extracted, "percent": percent}
