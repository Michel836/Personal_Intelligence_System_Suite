"""Database schema-version reporting (M019, phase 26).

Two version numbers are tracked:

* the FTS/schema version stored in ``fts_meta.schema_version`` (canonical,
  bumped by ``DatabaseManager``);
* a numeric ``PRAGMA user_version`` for the broader operational schema, which
  M019 sets once and migration checks compare against.

Migrations remain **additive**; nothing here drops a column or table.
"""
from __future__ import annotations

from typing import Any

#: Expected FTS/schema version (mirrors ``database.FTS_SCHEMA_VERSION``).
APP_SCHEMA_VERSION = "1"
#: Operational schema integer stored in ``PRAGMA user_version``.
OPS_USER_VERSION = 1


def _table_exists(conn: Any, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone()
    return row is not None


def db_schema_version(db: Any) -> dict[str, Any]:
    with db.get_connection() as conn:
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        fts_version = None
        if _table_exists(conn, "fts_meta"):
            row = conn.execute("SELECT value FROM fts_meta WHERE key='schema_version'").fetchone()
            fts_version = row[0] if row else None
    return {"fts_schema_version": fts_version, "user_version": user_version,
            "expected_fts_schema_version": APP_SCHEMA_VERSION,
            "expected_user_version": OPS_USER_VERSION}


def check_schema(db: Any) -> dict[str, Any]:
    info = db_schema_version(db)
    compatible = (
        (info["fts_schema_version"] in (None, APP_SCHEMA_VERSION)) and
        info["user_version"] <= OPS_USER_VERSION
    )
    notes = []
    if info["fts_schema_version"] is None:
        notes.append("fts_meta.schema_version absent (fresh or pre-M009 database)")
    if info["user_version"] == 0:
        notes.append("user_version unset; run 'pis maintenance schema-init'")
    if info["user_version"] > OPS_USER_VERSION:
        notes.append("database was written by a newer application version")
    return {**info, "compatible": compatible, "notes": notes}


def ensure_user_version(db: Any, *, version: int = OPS_USER_VERSION) -> int:
    """Set ``PRAGMA user_version`` when unset. Additive; never downgrades."""
    with db.get_connection() as conn:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current < version:
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.commit()
            return int(version)
        return current
