"""Local mono-user audit trail for sensitive operations (M015).

Operational audit only — not multi-user compliance infrastructure. Records the
action, target and a *non-sensitive* detail string. Never records raw document
content, queries that may contain PII, API keys or full sensitive values.
"""
from __future__ import annotations

from typing import Any, cast

ACTIONS = {
    "sensitive_document_viewed",
    "pii_count_viewed",
    "pii_filter_search",
    "redacted_preview",
    "redacted_export",
    "category_override",
    "remote_content_policy_changed",
    "privacy_setting_changed",
    "intel_pipeline_run",
}


class AuditTrail:
    def __init__(self, store: Any) -> None:
        self.store = store

    def record(self, action: str, *, target_type: str | None = None,
               target_id: int | None = None, detail: str | None = None,
               sensitivity: str = "normal") -> None:
        if action not in ACTIONS:
            action = f"custom:{action}"
        # Keep the detail short and never store content-like payloads.
        safe_detail = (detail or "")[:200]
        self.store.record_audit(action, target_type=target_type, target_id=target_id,
                                detail=safe_detail, sensitivity=sensitivity)

    def events(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self.store.audit_events(limit=limit))

    def prune(self, keep: int = 10000) -> int:
        return int(self.store.prune_audit(keep=keep))
