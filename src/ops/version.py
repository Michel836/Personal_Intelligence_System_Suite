"""Application version / commit resolution (M019).

Resolved once and cached. Never raises: a missing git binary or a source-only
checkout simply yields ``unknown`` for the commit.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Kept in sync with the operational schema/report contract.
APP_VERSION = "1.0.0"
OPS_VERSION = "m019.1"


@lru_cache(maxsize=1)
def git_commit(short: bool = True) -> str:
    try:
        args = ["git", "rev-parse"] + (["--short"] if short else []) + ["HEAD"]
        out = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                             timeout=5, check=False).stdout.strip()
        return out or "unknown"
    except Exception:  # noqa: BLE001 - version reporting must never fail
        return "unknown"


@lru_cache(maxsize=1)
def git_branch() -> str:
    try:
        return subprocess.run(["git", "branch", "--show-current"], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=5,
                              check=False).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def app_version() -> dict[str, str]:
    return {"app": APP_VERSION, "ops": OPS_VERSION, "commit": git_commit(),
            "branch": git_branch()}
