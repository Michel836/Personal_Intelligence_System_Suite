"""Stable API DTOs (M019, phase 4).

DTOs are deliberately decoupled from internal row shapes. PII is masked and
paths are redactable **by default**; sensitivity is returned as metadata only
(never a raw value).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_LIMIT = 100
DEFAULT_LIMIT = 25


def pagination(limit: Any, offset: Any, *, max_limit: int = MAX_LIMIT) -> tuple[int, int]:
    try:
        limit_i = int(limit)
    except (TypeError, ValueError):
        limit_i = DEFAULT_LIMIT
    try:
        offset_i = int(offset)
    except (TypeError, ValueError):
        offset_i = 0
    limit_i = max(1, min(limit_i, max_limit))
    offset_i = max(0, offset_i)
    return limit_i, offset_i


def mask_text(text: str | None) -> str | None:
    if text is None:
        return None
    from ..intel.redact import redact_text
    return redact_text(text)


def safe_path(path: str | None, *, redact_paths: bool, mask_pii: bool) -> str | None:
    if not path:
        return None
    if redact_paths:
        return f"<redacted>/{Path(path).name}"
    if mask_pii:
        return mask_text(path)
    return path


def sensitivity_of(db: Any, file_id: int) -> str | None:
    try:
        from ..intel import IntelStore
        return IntelStore(db).max_severity(int(file_id))
    except Exception:  # noqa: BLE001 - intel tables may be absent
        return None


def file_dto(db: Any, row: dict[str, Any], *, mask_pii: bool = True,
             redact_paths: bool = True, include_sensitivity: bool = False) -> dict[str, Any]:
    file_id = int(row["id"])
    out: dict[str, Any] = {
        "id": file_id,
        "filename": mask_text(row.get("filename")) if mask_pii else row.get("filename"),
        "extension": row.get("extension"),
        "size_bytes": row.get("size_bytes"),
        "modified_at": row.get("modified_at"),
        "file_type": row.get("file_type"),
        "priority": row.get("priority"),
        "document_kind": row.get("document_kind"),
        "state": row.get("state") or "ACTIVE",
        "path": safe_path(row.get("path"), redact_paths=redact_paths, mask_pii=mask_pii),
        "pii_masked": bool(mask_pii),
    }
    if include_sensitivity:
        out["sensitivity"] = sensitivity_of(db, file_id)
    return out


def document_dto(db: Any, row: dict[str, Any], *, preview_chars: int = 500,
                 mask_pii: bool = True, redact_paths: bool = True) -> dict[str, Any]:
    out = file_dto(db, row, mask_pii=mask_pii, redact_paths=redact_paths,
                   include_sensitivity=True)
    content = row.get("content_text") or ""
    if content:
        snippet = content[: max(0, preview_chars)]
        out["preview"] = mask_text(snippet) if mask_pii else snippet
        out["preview_truncated"] = len(content) > len(snippet)
    else:
        out["preview"] = None
        out["preview_truncated"] = False
    out["extraction_state"] = row.get("extraction_state")
    return out
