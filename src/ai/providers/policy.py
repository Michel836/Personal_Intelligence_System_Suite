"""Remote-content privacy policy (M012-A).

The policy bounds what may be transmitted to a *remote* provider. Local
providers are never restricted. The router enforces the policy at the provider
boundary, so application/UI code cannot bypass it.
"""
from __future__ import annotations

import os
from enum import Enum


class RemoteContentPolicy(str, Enum):
    NEVER = "never"
    METADATA_ONLY = "metadata_only"
    EXTRACTED_TEXT = "extracted_text"
    FULL_CONTEXT = "full_context"

    @classmethod
    def from_env(cls, value: str | None = None) -> "RemoteContentPolicy":
        raw = (value if value is not None else os.environ.get("PIS_REMOTE_CONTENT_POLICY", "never"))
        raw = (raw or "never").strip().lower()
        try:
            return cls(raw)
        except ValueError:
            return cls.NEVER

    @property
    def allows_remote(self) -> bool:
        """Whether any non-empty payload may reach a remote provider."""
        return self is not RemoteContentPolicy.NEVER

    @property
    def allows_extracted_text(self) -> bool:
        """Whether extracted document body text may reach a remote provider."""
        return self in (RemoteContentPolicy.EXTRACTED_TEXT, RemoteContentPolicy.FULL_CONTEXT)

    @property
    def allows_full_context(self) -> bool:
        return self is RemoteContentPolicy.FULL_CONTEXT


# Default is privacy-safe: nothing leaves the process for a remote provider.
DEFAULT_POLICY = RemoteContentPolicy.NEVER
