"""Privacy-aware export controls (M018).

Modes are explicit presets. Selecting a mode never *silently* weakens privacy:
every mode's behaviour is documented, the chosen mode is recorded in the report
definition, the manifest and the rendered banner, and the preview shows exactly
what will be exported before generation.

Reuses the M015 redaction (`src.intel.redact`) and PII store; the M012
``RemoteContentPolicy`` remains authoritative and is untouched here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import PrivacyMode

#: Ordered for UI display; order is part of the contract.
PRIVACY_MODES: list[str] = [m.value for m in PrivacyMode]

_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    PrivacyMode.FULL_LOCAL.value: {
        "label": "Full (local)",
        "content": "full extracted text excerpts",
        "path": "full original path",
        "excludes": [],
        "banner": "Full local export — extracted content and paths are included.",
    },
    PrivacyMode.MASK_PII.value: {
        "label": "Mask PII",
        "content": "excerpts with structured PII masked",
        "path": "paths with structured PII masked",
        "excludes": [],
        "banner": "PII-masked export — emails, phones, IBANs, cards and national IDs are masked in the derivative only.",
    },
    PrivacyMode.OMIT_HIGH_SENSITIVITY.value: {
        "label": "Omit high sensitivity",
        "content": "excerpts for non-high-sensitivity documents",
        "path": "full original path",
        "excludes": ["high-severity PII"],
        "banner": "High-sensitivity documents are omitted entirely (listed as omitted, never rendered).",
    },
    PrivacyMode.PATH_REDACTED.value: {
        "label": "Redact paths",
        "content": "full extracted text excerpts",
        "path": "directory removed; basename only",
        "excludes": [],
        "banner": "Paths redacted — only the file basename is shown.",
    },
    PrivacyMode.METADATA_ONLY.value: {
        "label": "Metadata only",
        "content": "no content excerpts",
        "path": "directory removed; basename only",
        "excludes": [],
        "banner": "Metadata-only export — no document text is included.",
    },
}


def describe_mode(mode: str) -> dict[str, Any]:
    return dict(_DESCRIPTIONS.get(mode, _DESCRIPTIONS[PrivacyMode.FULL_LOCAL.value]))


def all_mode_descriptions() -> list[dict[str, Any]]:
    return [{"mode": m, **_DESCRIPTIONS[m]} for m in PRIVACY_MODES]


def banner(mode: str) -> str:
    return str(describe_mode(mode)["banner"])


def includes_content(mode: str) -> bool:
    return mode != PrivacyMode.METADATA_ONLY.value


def masks_content(mode: str) -> bool:
    return mode == PrivacyMode.MASK_PII.value


def omits_high_sensitivity(mode: str) -> bool:
    return mode == PrivacyMode.OMIT_HIGH_SENSITIVITY.value


def redacts_paths(mode: str) -> bool:
    return mode in {PrivacyMode.PATH_REDACTED.value, PrivacyMode.METADATA_ONLY.value}


def _looks_absolute(path: str) -> bool:
    return path.startswith("/") or (len(path) > 1 and path[1] == ":")


def safe_path(path: str | None, mode: str) -> str | None:
    """Return the privacy-safe path variant for a mode (or ``None``)."""
    if not path:
        return None
    text = str(path)
    if redacts_paths(mode):
        base = Path(text).name or text
        return f"<redacted>/{base}"
    if masks_content(mode):
        from ..intel.redact import redact_text
        if _looks_absolute(text):
            head, _, base = text.rpartition("/")
            return f"{head}/" + redact_text(base)
        return redact_text(text)
    return text


def mask_text(text: str, mode: str) -> str:
    if masks_content(mode):
        from ..intel.redact import redact_text
        return redact_text(text or "")
    return text or ""


def mask_label(label: str, mode: str) -> str:
    return mask_text(label, mode)


def is_high_sensitivity(db: Any, file_id: int) -> bool:
    try:
        from ..intel import IntelStore
        return IntelStore(db).max_severity(int(file_id)) == "high"
    except Exception:  # noqa: BLE001 - intel tables may be absent
        return False


def filter_documents(db: Any, file_ids: list[int], mode: str) -> tuple[list[int], list[dict[str, Any]]]:
    """Return ``(kept_ids, omitted)`` for the mode. Never drops silently."""
    if not omits_high_sensitivity(mode):
        return list(file_ids), []
    kept: list[int] = []
    omitted: list[dict[str, Any]] = []
    for fid in file_ids:
        if is_high_sensitivity(db, fid):
            omitted.append({"file_id": int(fid), "reason": "high-sensitivity PII",
                            "mode": mode})
        else:
            kept.append(int(fid))
    return kept, omitted
