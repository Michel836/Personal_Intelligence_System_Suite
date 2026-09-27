"""PII awareness for the AI provider router (M015).

The M012 ``RemoteContentPolicy`` remains **authoritative**. PII metadata can
only ever *warn* the user when they explicitly choose to send context remotely;
it never relaxes, overrides or auto-changes a policy.
"""
from __future__ import annotations

from typing import Any


def remote_policy_state(policy: Any) -> dict[str, Any]:
    return {
        "value": policy.value,
        "allows_remote": policy.allows_remote,
        "allows_extracted_text": policy.allows_extracted_text,
        "allows_full_context": policy.allows_full_context,
    }


def remote_warning(policy: Any, findings: list[dict[str, Any]]) -> str | None:
    """Return a warning when remote sending is explicitly enabled and PII exists.

    Returns ``None`` when the policy forbids remote content (nothing to warn
    about) or no PII is present. Never mutates the policy.
    """
    if not policy.allows_remote:
        return None
    sensitive = [f for f in findings if f.get("severity") in {"medium", "high"}]
    if not sensitive:
        return None
    types = sorted({f.get("type", "pii") for f in sensitive})
    return ("This document contains possible sensitive identifiers "
            f"({', '.join(types)}); sending it to a remote provider may expose them. "
            "The privacy policy is unchanged — lower it or keep the content local.")
