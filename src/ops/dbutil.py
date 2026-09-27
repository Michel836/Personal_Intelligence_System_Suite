"""Small, dependency-free database helpers shared by the ops layer."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def has_table(db: Any, name: str) -> bool:
    with db.get_connection() as conn:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                           (name,)).fetchone()
    return row is not None


def table_count(db: Any, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int | None:
    if not has_table(db, table):
        return None
    clause = f" WHERE {where}" if where else ""
    with db.get_connection() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}{clause}", params).fetchone()[0])


def db_size(db: Any) -> int:
    path = Path(getattr(db, "db_path", ""))
    try:
        return path.stat().st_size if path.exists() else 0
    except OSError:
        return 0


def page_stats(db: Any) -> dict[str, Any]:
    with db.get_connection() as conn:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        freelist = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    return {"page_size": page_size, "page_count": page_count,
            "freelist_pages": freelist, "reclaimable_bytes": freelist * page_size,
            "journal_mode": journal}
