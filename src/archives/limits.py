"""Configurable hard limits and policies for archive processing (M009J.6/.18)."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Bump when member-selection / extraction semantics change so that a rescan can
# explicitly re-index archives that were processed by an older version.
ARCHIVE_PROCESSING_VERSION = "1"

# Processing policies for member content extraction (M009J.18).
POLICY_METADATA_ONLY = "METADATA_ONLY"
POLICY_SAFE_SUPPORTED = "SAFE_SUPPORTED_MEMBERS"
POLICY_FULL_WITHIN_LIMITS = "FULL_WITHIN_LIMITS"
_POLICIES = {POLICY_METADATA_ONLY, POLICY_SAFE_SUPPORTED, POLICY_FULL_WITHIN_LIMITS}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class ArchiveLimits:
    """Immutable safety budget shared across nested archives."""

    max_depth: int = 3
    max_members: int = 5000
    max_member_bytes: int = 64 * 1024 * 1024
    max_total_uncompressed: int = 1024 * 1024 * 1024
    max_ratio: int = 200
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "ArchiveLimits":
        return cls(
            max_depth=_env_int("PIS_ARCHIVE_MAX_DEPTH", 3),
            max_members=_env_int("PIS_ARCHIVE_MAX_MEMBERS", 5000),
            max_member_bytes=_env_int("PIS_ARCHIVE_MAX_MEMBER_BYTES", 64 * 1024 * 1024),
            max_total_uncompressed=_env_int(
                "PIS_ARCHIVE_MAX_TOTAL_UNCOMPRESSED", 1024 * 1024 * 1024
            ),
            max_ratio=_env_int("PIS_ARCHIVE_MAX_RATIO", 200),
            timeout=float(_env_int("PIS_ARCHIVE_TIMEOUT", 30)),
        )


@dataclass(frozen=True)
class ArchivePolicy:
    """Enablement + extraction policy resolved from the environment."""

    enabled: bool = True
    policy: str = POLICY_SAFE_SUPPORTED

    @classmethod
    def from_env(cls) -> "ArchivePolicy":
        policy = os.environ.get("PIS_ARCHIVE_POLICY", POLICY_SAFE_SUPPORTED).strip().upper()
        if policy not in _POLICIES:
            policy = POLICY_SAFE_SUPPORTED
        return cls(enabled=_env_bool("PIS_ARCHIVE_ENABLED", True), policy=policy)

    @property
    def index_members(self) -> bool:
        return self.enabled

    @property
    def extract_content(self) -> bool:
        return self.enabled and self.policy in {POLICY_SAFE_SUPPORTED, POLICY_FULL_WITHIN_LIMITS}
