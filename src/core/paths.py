"""Canonical path resolution for 36TB Intelligence.

The application is mono-user and local-first. Runtime state must never depend on
the current working directory: running ``pis`` from ``/tmp`` and from ``$HOME``
must address the *same* database.

Resolution order (highest first):

1. explicit ``--db`` / argument passed by the caller;
2. ``PIS_DB_PATH`` / ``PIS_DATA_DIR`` environment variables;
3. XDG base directories (``$XDG_DATA_HOME/pis``, default
   ``~/.local/share/pis``).

Legacy ``./data`` trees from pre-XDG versions are migrated once (moved when
possible, copied otherwise) the first time a command resolves the default
database. Set ``PIS_NO_AUTO_MIGRATE=1`` to disable that and use
``pis migrate-data`` explicitly.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable

APP_NAME = "pis"
AUTO_MIGRATE_ENV = "PIS_NO_AUTO_MIGRATE"
_MIGRATION_MARKER = ".migrated-from"


# --------------------------------------------------------------------------
# Base directories
# --------------------------------------------------------------------------
def repo_root() -> Path:
    """Return the source checkout root (or the install prefix parent)."""
    return Path(__file__).resolve().parents[2]


def _xdg(env_name: str, fallback: Path) -> Path:
    raw = os.environ.get(env_name)
    return Path(raw).expanduser() if raw else fallback


def data_dir() -> Path:
    """Absolute application data directory (database, reports, logs)."""
    explicit = os.environ.get("PIS_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    base = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return (base / APP_NAME).resolve()


def state_dir() -> Path:
    """Absolute application state directory (job status, locks)."""
    explicit = os.environ.get("PIS_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    base = _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state")
    return (base / APP_NAME).resolve()


def cache_dir() -> Path:
    explicit = os.environ.get("PIS_CACHE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    base = _xdg("XDG_CACHE_HOME", Path.home() / ".cache")
    return (base / APP_NAME).resolve()


def indexes_dir() -> Path:
    return data_dir() / "indexes"


def reports_dir() -> Path:
    return data_dir() / "reports"


def logs_dir() -> Path:
    return data_dir() / "logs"


def embeddings_dir() -> Path:
    """Embedding matrix store + model cache.

    Co-located with the database (``<data>/cache/embeddings``) so a trial data
    directory is fully self-contained and backup/restore covers vectors too.
    """
    explicit = os.environ.get("PIS_EMBEDDING_STORE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return data_dir() / "cache" / "embeddings"


def export_dir() -> Path:
    explicit = os.environ.get("PIS_EXPORT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".pis-exports"


def backup_dir() -> Path:
    explicit = os.environ.get("PIS_BACKUP_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".pis-backups"


def default_db_path() -> str:
    """Absolute default database path (``$DATA/indexes/files.db``)."""
    return str(indexes_dir() / "files.db")


def resolve_db_path(
    explicit: str | Path | None = None, *, migrate: bool = True
) -> Path:
    """Resolve the database path, optionally running the legacy migration.

    ``migrate=False`` is used by read-only diagnostics (``--json`` metadata,
    ``migrate-data --dry-run``) so displaying a path never mutates the user's
    data. An explicit path is never migrated nor rewritten.
    """
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_absolute() else path.resolve()
    env = os.environ.get("PIS_DB_PATH")
    if env:
        path = Path(env).expanduser()
        return path if path.is_absolute() else path.resolve()
    if migrate:
        maybe_migrate_legacy_data()
    return Path(default_db_path())


# --------------------------------------------------------------------------
# Directory creation
# --------------------------------------------------------------------------
def ensure_layout() -> dict[str, str]:
    """Create the canonical directory layout and return its absolute paths."""
    layout = {
        "data_dir": data_dir(),
        "indexes_dir": indexes_dir(),
        "reports_dir": reports_dir(),
        "logs_dir": logs_dir(),
        "state_dir": state_dir(),
        "cache_dir": cache_dir(),
        "embeddings_dir": embeddings_dir(),
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return {name: str(path) for name, path in layout.items()}


# --------------------------------------------------------------------------
# Legacy migration
# --------------------------------------------------------------------------
def legacy_data_candidates(explicit: str | Path | None = None) -> list[Path]:
    """Return existing legacy ``data`` directories, most specific first."""
    if explicit:
        candidates = [Path(explicit).expanduser()]
    else:
        candidates = [repo_root() / "data", Path.cwd() / "data"]
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _iter_legacy_files(source: Path) -> Iterable[Path]:
    for root, _dirs, files in os.walk(source):
        for name in files:
            # Ignore volatile SQLite sidecars; the DB is copied consistently.
            if name.endswith(("-wal", "-shm")):
                continue
            yield Path(root) / name


def _copy_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _bind_store_dir(target: Path) -> None:
    """Point a migrated database at the migrated embedding store (best effort)."""
    db_path = target / "indexes" / "files.db"
    if not db_path.is_file():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "semantic_meta" in tables:
                conn.execute(
                    "INSERT OR REPLACE INTO semantic_meta(key, value) "
                    "VALUES ('store_dir', ?)",
                    (str(target / "cache" / "embeddings"),),
                )
                conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        # A read-only or older database must not block the migration.
        pass


def migrate_legacy_data(
    source: str | Path | None = None,
    *,
    move: bool = True,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Migrate a legacy ``./data`` tree into the XDG data directory.

    SQLite databases are copied through the backup API (consistent snapshot);
    other files are copied with metadata. ``move=True`` removes the source tree
    only after a fully successful migration.
    """
    candidates = legacy_data_candidates(source)
    if not candidates:
        return {"status": "NOT_FOUND", "source": None, "target": str(data_dir())}
    legacy = candidates[0]
    target = data_dir()
    if _is_within(target, legacy) or _is_within(legacy, target):
        return {
            "status": "SKIPPED",
            "reason": "source and target overlap",
            "source": str(legacy),
            "target": str(target),
        }

    files = list(_iter_legacy_files(legacy))
    report: dict[str, Any] = {
        "status": "PLANNED" if dry_run else "MIGRATED",
        "source": str(legacy),
        "target": str(target),
        "move": bool(move),
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files if p.exists()),
        "sqlite": 0,
        "skipped": [],
        "errors": [],
    }
    if dry_run:
        return report

    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        relative = path.relative_to(legacy)
        destination = target / relative
        if destination.exists() and not overwrite:
            report["skipped"].append(str(relative))
            continue
        try:
            if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                if destination.exists():
                    destination.unlink()
                _copy_sqlite(path, destination)
                report["sqlite"] += 1
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
        except Exception as exc:  # noqa: BLE001 - keep migrating, report later
            report["errors"].append({"path": str(relative), "error": str(exc)})

    _bind_store_dir(target)
    marker = target / _MIGRATION_MARKER
    with contextlib.suppress(OSError):
        marker.write_text(
            json.dumps({"source": str(legacy), "files": len(files)}), encoding="utf-8"
        )

    if move and not report["errors"] and not report["skipped"]:
        with contextlib.suppress(OSError):
            shutil.rmtree(legacy)
        report["status"] = "MOVED"
    elif report["errors"]:
        report["status"] = "PARTIAL"
    return report


def maybe_migrate_legacy_data() -> dict[str, Any] | None:
    """Auto-migrate a legacy tree once, when safe.

    Disabled by ``PIS_NO_AUTO_MIGRATE=1``, when an explicit data directory is
    configured, or when the target database already exists. Returns the
    migration report when a migration happened.
    """
    if os.environ.get(AUTO_MIGRATE_ENV, "").lower() in {"1", "true", "yes"}:
        return None
    if os.environ.get("PIS_DATA_DIR") or os.environ.get("PIS_DB_PATH"):
        return None
    target_db = indexes_dir() / "files.db"
    if target_db.exists():
        return None
    for legacy in legacy_data_candidates():
        if not (legacy / "indexes" / "files.db").exists():
            continue
        # Only auto-migrate small/medium trees silently; large trees still
        # migrate but the caller sees the report (CLI prints it).
        try:
            report = migrate_legacy_data(legacy, move=True)
        except Exception as exc:  # noqa: BLE001 - never block the command
            return {"status": "FAILED", "source": str(legacy), "error": str(exc)}
        if report.get("status") in {"MOVED", "MIGRATED", "PARTIAL"}:
            return report
    return None
