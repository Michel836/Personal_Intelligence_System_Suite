"""Provenance assembly for report sources (M018).

Every factual item carries how it was obtained. We never claim a document date,
page number or hash that the underlying data does not actually provide:

* ``KNOWN``      — read directly (filesystem mtime, a real email header date, a
                   stored content hash, an extractor-reported location);
* ``DERIVED``    — computed from a canonical service (version rank, relation);
* ``INFERRED``   — heuristic (e.g. a filename version marker);
* ``UNAVAILABLE``— not provided by any source; reported as such, never invented.
"""
from __future__ import annotations

from typing import Any

from .citations import CitationRegistry
from .models import ProvenanceClass, SourceRef
from .privacy import mask_label, safe_path

_ROW_COLUMNS = (
    "id", "path", "filename", "extension", "size_bytes", "document_kind",
    "archive_parent_id", "modified_at", "created_at", "state", "content_extracted",
    "extraction_state",
)

#: Optional tables (M014/M015/M017) may be absent on a fresh database. Probing
#: avoids triggering the DB layer's error logging/retry for a missing table.
_TABLE_CACHE: dict[str, set[str]] = {}


def table_names(db: Any) -> set[str]:
    key = str(getattr(db, "db_path", "?"))
    cached = _TABLE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        with db.get_connection() as conn:
            names = {str(r[0]) for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    except Exception:  # noqa: BLE001
        names = set()
    _TABLE_CACHE[key] = names
    return names


def has_table(db: Any, name: str) -> bool:
    return name in table_names(db)


def file_row(db: Any, file_id: int) -> dict[str, Any] | None:
    cols = ", ".join(_ROW_COLUMNS)
    with db.get_connection() as conn:
        row = conn.execute(f"SELECT {cols} FROM files WHERE id=?", (int(file_id),)).fetchone()
    return dict(row) if row is not None else None


def _email_header_date(db: Any, file_id: int) -> str | None:
    if not has_table(db, "email_threads"):
        return None
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT date FROM email_threads WHERE file_id=?",
                               (int(file_id),)).fetchone()
        return (row[0] or None) if row else None
    except Exception:  # noqa: BLE001 - M017 table may be absent
        return None


def _version_marker_date(path: str) -> str | None:
    try:
        from ..dedup.versions import version_marker
        mk = version_marker(path)
        if mk and mk.get("kind") == "date":
            return str(mk["value"])[:10]
    except Exception:  # noqa: BLE001
        return None
    return None


def resolve_date(db: Any, row: dict[str, Any]) -> tuple[str | None, str | None, str]:
    """Return ``(date, source, provenance_class)`` without inventing anything."""
    header = _email_header_date(db, int(row["id"]))
    if header:
        return header, "email_header", ProvenanceClass.KNOWN.value
    marker = _version_marker_date(str(row.get("path") or ""))
    if marker:
        return marker, "filename_version_marker", ProvenanceClass.INFERRED.value
    for col in ("modified_at", "created_at"):
        value = row.get(col)
        if value:
            return str(value)[:10], col, ProvenanceClass.KNOWN.value
    return None, None, ProvenanceClass.UNAVAILABLE.value


def extraction_state(row: dict[str, Any]) -> str:
    if row.get("extraction_state"):
        return str(row["extraction_state"])
    if row.get("content_extracted"):
        return "EXTRACTED"
    return "NOT_EXTRACTED"


def content_hash(db: Any, file_id: int) -> dict[str, Any] | None:
    if not has_table(db, "content_hashes"):
        return None
    try:
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT digest, algorithm, state FROM content_hashes WHERE file_id=?",
                (int(file_id),)).fetchone()
        return dict(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def build_source(registry: CitationRegistry, db: Any, file_id: int, mode: str, *,
                 label: str | None = None, score: float | None = None,
                 location: str | None = None,
                 relations: list[dict[str, Any]] | None = None,
                 note: str | None = None, unavailable: bool = False) -> SourceRef:
    """Register a document source with full provenance.

    A file that is missing from the DB is registered as *unavailable* so a
    citation to it stays valid and explicitly marked, never fabricated.
    """
    row = file_row(db, file_id)
    if row is None:
        return registry.document(
            int(file_id), label=label or f"document {file_id}", unavailable=True,
            provenance=ProvenanceClass.UNAVAILABLE.value, score=score,
            relations=relations, note=note or "source row not found")
    date, date_source, date_class = resolve_date(db, row)
    display = label or str(row.get("filename") or f"document {file_id}")
    return registry.document(
        int(file_id),
        label=mask_label(display, mode),
        path=safe_path(row.get("path"), mode),
        date=date, date_source=date_source, date_class=date_class,
        extraction_state=extraction_state(row),
        score=score, location=location, relations=relations,
        provenance=ProvenanceClass.KNOWN.value, unavailable=unavailable, note=note)
