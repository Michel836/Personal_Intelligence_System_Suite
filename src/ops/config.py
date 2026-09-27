"""Effective configuration + precedence model (M019, phase 18).

Precedence (highest first):

1. **Explicit argument** passed to a CLI/API call (never overridden);
2. **Process environment** (``os.environ`` / ``PIS_*``) — this is what the
   launcher sets from profile defaults, so profile defaults never clobber an
   operator value;
3. **``.env`` file** — only read by the legacy pydantic ``Settings`` object; the
   canonical runtime is env-driven, so ``.env`` is documented but not silently
   injected here;
4. **Code defaults**.

Secrets are never emitted: any key whose name contains a secret hint is
replaced by a ``set``/``unset`` marker.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

SECRET_HINTS = ("SECRET", "PASSWORD", "PASSWD", "TOKEN", "API_KEY", "APIKEY",
                "CREDENTIAL", "PRIVATE_KEY")

#: Canonical operations environment variables and their defaults.
DEFAULTS: dict[str, str] = {
    "PIS_DB_PATH": "data/indexes/files.db",
    "PIS_EMBEDDING_STORE_DIR": "data/cache/embeddings",
    "PIS_EXPORT_DIR": str(Path.home() / ".pis-exports"),
    "PIS_BACKUP_DIR": str(Path.home() / ".pis-backups"),
    "PIS_API_HOST": "127.0.0.1",
    "PIS_API_PORT": "8600",
    "PIS_REMOTE_CONTENT_POLICY": "never",
    "PIS_AI_MODE": "auto",
    "PIS_VECTOR_BACKEND": "matrix",
    "PIS_LOG_LEVEL": "INFO",
}

PRECEDENCE_ORDER = ["explicit", "environment", "dotenv", "default"]


def _looks_secret(name: str) -> bool:
    upper = name.upper()
    return any(hint in upper for hint in SECRET_HINTS)


def redact_secrets(mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with secret-looking values replaced by a marker."""
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if _looks_secret(str(key)):
            text = "" if value is None else str(value)
            out[key] = f"***set*** (len={len(text)})" if text else "***unset***"
        else:
            out[key] = value
    return out


def resolve_setting(name: str, *,
                    explicit: str | None = None) -> tuple[str, str]:
    """Return ``(value, source)`` for one variable following the precedence."""
    if explicit is not None:
        return str(explicit), "explicit"
    if name in os.environ and os.environ[name] != "":
        return os.environ[name], "environment"
    return DEFAULTS.get(name, ""), "default"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _abs(value: str) -> str:
    if not value:
        return value
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else (repo_root() / path))


def effective_config(*, include_paths: bool = True) -> dict[str, Any]:
    """Return the resolved operational config with secrets redacted."""
    resolved: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for name in DEFAULTS:
        value, source = resolve_setting(name)
        resolved[name] = value
        sources[name] = source
    out: dict[str, Any] = {
        "values": redact_secrets(resolved),
        "sources": sources,
        "precedence": PRECEDENCE_ORDER,
        "privacy_policy": resolved["PIS_REMOTE_CONTENT_POLICY"],
        "ai_mode": resolved["PIS_AI_MODE"],
        "api_host": resolved["PIS_API_HOST"],
        "api_port": resolved["PIS_API_PORT"],
        "vector_backend": resolved["PIS_VECTOR_BACKEND"],
    }
    for extra in ("PIS_PG_URL", "PIS_OLLAMA_URL", "OLLAMA_BASE_URL", "PIS_API_KEY"):
        if extra in os.environ:
            out["values"][extra] = redact_secrets({extra: os.environ[extra]})[extra]
    if include_paths:
        out["paths"] = {
            "db": _abs(resolved["PIS_DB_PATH"]),
            "embedding_store": _abs(resolved["PIS_EMBEDDING_STORE_DIR"]),
            "export_dir": _abs(resolved["PIS_EXPORT_DIR"]),
            "backup_dir": _abs(resolved["PIS_BACKUP_DIR"]),
            "temp_dir": tempfile.gettempdir(),
            "repo_root": str(repo_root()),
        }
    return out


def config_precedence() -> list[dict[str, str]]:
    return [
        {"level": "explicit", "meaning": "CLI flag / API parameter passed for this call"},
        {"level": "environment", "meaning": "os.environ (PIS_* / profile defaults set by the launcher)"},
        {"level": "dotenv", "meaning": ".env — read only by the legacy pydantic Settings object"},
        {"level": "default", "meaning": "code default in src.ops.config.DEFAULTS"},
    ]
