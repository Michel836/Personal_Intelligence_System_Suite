"""M019 operations layer: local API, CLI, maintenance, backup/restore, doctor.

Mono-user, local-only. Nothing here mutates the source corpus, requires a
network service, or performs a destructive operation without an explicit
action. The canonical database (SQLite) and semantic matrix store remain the
sources of truth.
"""
from __future__ import annotations

from .backup import (
    BackupResult,
    RestoreResult,
    create_backup,
    restore_backup,
    verify_backup,
)
from .config import config_precedence, effective_config, redact_secrets
from .doctor import run_doctor
from .health import health_report
from .maintenance import MaintenanceService
from .schema import APP_SCHEMA_VERSION, check_schema, db_schema_version
from .version import app_version

__all__ = [
    "app_version", "effective_config", "config_precedence", "redact_secrets",
    "run_doctor", "health_report", "MaintenanceService",
    "create_backup", "verify_backup", "restore_backup",
    "BackupResult", "RestoreResult",
    "APP_SCHEMA_VERSION", "check_schema", "db_schema_version",
]
