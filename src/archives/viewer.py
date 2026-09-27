"""Archive-aware viewer helpers (M009J.17).

Pure data helpers used by the UI: a bounded container summary, a paged member
list and a single-member detail with a short content preview. No helper ever
materializes a large member just to render it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.database import DatabaseManager

PREVIEW_CHARS = 4000


def human_size(num: Optional[int]) -> str:
    size = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def container_summary(db: DatabaseManager, parent_id: int) -> Optional[Dict[str, Any]]:
    """Return a bounded summary of an archive container (no member reads)."""
    state = db.get_archive_index_state(parent_id)
    if state is None:
        return None
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id, path, filename, size_bytes FROM files WHERE id = ?", (parent_id,)
        ).fetchone()
        counts = conn.execute(
            """SELECT
                   SUM(CASE WHEN member_state = 'ACTIVE' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN extraction_state = 'EXTRACTED' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN member_encrypted = 1 THEN 1 ELSE 0 END)
               FROM files WHERE document_kind = 'ARCHIVE_MEMBER' AND archive_parent_id = ?""",
            (parent_id,),
        ).fetchone()
    if row is None:
        return None
    active = int(counts[0] or 0)
    extracted = int(counts[1] or 0)
    encrypted = int(counts[2] or 0)
    return {
        "id": parent_id,
        "path": row["path"],
        "filename": row["filename"],
        "format": state.get("archive_format"),
        "status": state.get("archive_status"),
        "member_count": int(state.get("archive_member_count") or 0),
        "active_member_count": active,
        "extracted_member_count": extracted,
        "encrypted_member_count": int(state.get("archive_encrypted_count") or encrypted or 0),
        "compressed_size": int(state.get("archive_compressed_size") or 0),
        "expanded_size": int(state.get("archive_expanded_size") or 0),
        "compressed_human": human_size(state.get("archive_compressed_size")),
        "expanded_human": human_size(state.get("archive_expanded_size")),
        "indexed_at": state.get("archive_indexed_at"),
        "fingerprint": state.get("archive_fingerprint"),
        "processing_version": state.get("archive_processing_version"),
    }


def list_container_members(
    db: DatabaseManager, parent_id: int, *, limit: int = 200, offset: int = 0,
    include_missing: bool = False,
) -> List[Dict[str, Any]]:
    """Paged, bounded listing of a container's virtual members."""
    clause = "" if include_missing else "AND member_state = 'ACTIVE'"
    with db.get_connection() as conn:
        rows = conn.execute(
            f"""SELECT id, archive_member_path, member_type, member_uncompressed_size,
                       member_compressed_size, member_encrypted, extraction_state,
                       member_state, extension
                FROM files
                WHERE document_kind = 'ARCHIVE_MEMBER' AND archive_parent_id = ? {clause}
                ORDER BY archive_member_path ASC LIMIT ? OFFSET ?""",
            (parent_id, int(limit), int(offset)),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "member_path": r["archive_member_path"],
            "member_type": r["member_type"],
            "size": r["member_uncompressed_size"],
            "size_human": human_size(r["member_uncompressed_size"]),
            "extraction_state": r["extraction_state"],
            "member_state": r["member_state"],
            "is_encrypted": bool(r["member_encrypted"]),
            "extension": r["extension"],
        }
        for r in rows
    ]


def member_detail(db: DatabaseManager, member_id: int, *, preview_chars: int = PREVIEW_CHARS) -> Optional[Dict[str, Any]]:
    """Return a single member's metadata plus a bounded content preview."""
    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT m.*, p.path AS parent_path, p.filename AS parent_name
               FROM files m JOIN files p ON p.id = m.archive_parent_id
               WHERE m.id = ? AND m.document_kind = 'ARCHIVE_MEMBER'""",
            (member_id,),
        ).fetchone()
    if row is None:
        return None
    content = row["content_text"] or ""
    return {
        "id": member_id,
        "parent_id": row["archive_parent_id"],
        "parent_archive": row["parent_path"],
        "parent_name": row["parent_name"],
        "virtual_path": row["path"],
        "member_path": row["archive_member_path"],
        "member_type": row["member_type"],
        "format": row["archive_format"],
        "depth": row["archive_depth"],
        "size": row["member_uncompressed_size"],
        "compressed_size": row["member_compressed_size"],
        "size_human": human_size(row["member_uncompressed_size"]),
        "crc": row["member_crc"],
        "is_encrypted": bool(row["member_encrypted"]),
        "extraction_state": row["extraction_state"],
        "member_state": row["member_state"],
        "content_extracted": bool(row["content_extracted"]),
        "preview": content[:preview_chars],
        "preview_truncated": len(content) > preview_chars,
    }
