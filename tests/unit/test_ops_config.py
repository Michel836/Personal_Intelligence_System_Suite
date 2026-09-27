"""Operational config precedence + secret redaction (M019)."""
from __future__ import annotations

from src.ops.config import (
    config_precedence,
    effective_config,
    redact_secrets,
    resolve_setting,
)


def test_redact_secrets_masks_secret_like_keys() -> None:
    out = redact_secrets({
        "PIS_API_KEY": "supersecretvalue",
        "DATABASE_PASSWORD": "hunter2",
        "PIS_DB_PATH": "/data/files.db",
        "EMPTY_TOKEN": "",
    })
    assert "supersecretvalue" not in out["PIS_API_KEY"]
    assert out["PIS_API_KEY"].startswith("***set***")
    assert "hunter2" not in out["DATABASE_PASSWORD"]
    assert out["PIS_DB_PATH"] == "/data/files.db"
    assert out["EMPTY_TOKEN"] == "***unset***"


def test_precedence_explicit_over_environment_over_default(monkeypatch) -> None:
    monkeypatch.setenv("PIS_DB_PATH", "/from/env.db")
    assert resolve_setting("PIS_DB_PATH", explicit="/explicit.db") == ("/explicit.db", "explicit")
    assert resolve_setting("PIS_DB_PATH") == ("/from/env.db", "environment")
    monkeypatch.delenv("PIS_DB_PATH", raising=False)
    value, source = resolve_setting("PIS_DB_PATH")
    assert source == "default" and value == "data/indexes/files.db"


def test_effective_config_is_redacted_and_has_paths(monkeypatch) -> None:
    monkeypatch.setenv("PIS_API_KEY", "topsecret")
    config = effective_config(include_paths=True)
    assert "topsecret" not in str(config)
    assert config["values"]["PIS_API_KEY"].startswith("***set***")
    assert {"db", "embedding_store", "export_dir", "backup_dir", "temp_dir"} <= set(config["paths"])
    assert config["precedence"] == ["explicit", "environment", "dotenv", "default"]
    assert config_precedence()[0]["level"] == "explicit"
