"""Safe aggregate health report (M019, phase 11).

Only aggregate, non-sensitive state is returned. Private paths are omitted
unless ``include_paths=True`` (used locally by the CLI/UI, never by the
default API response).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import effective_config
from .schema import check_schema
from .version import app_version

_DEFAULT_STORE_DIR = "data/cache/embeddings"


def _store_base_dir() -> Path:
    raw = os.environ.get("PIS_EMBEDDING_STORE_DIR") or _DEFAULT_STORE_DIR
    path = Path(raw)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def semantic_status() -> dict[str, Any]:
    """Read the matrix store metadata without loading the matrix or a model."""
    base = _store_base_dir()
    stores: list[dict[str, Any]] = []
    if base.is_dir():
        for child in sorted(base.iterdir()):
            meta_path = child / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                meta = {}
            stores.append({
                "model_key": meta.get("model_key") or child.name,
                "model_name": meta.get("model_name"),
                "dim": meta.get("dim"),
                "count": meta.get("count"),
                "capacity": meta.get("capacity"),
                "dtype": meta.get("dtype"),
                "normalized": meta.get("normalized"),
                "matrix_present": (child / "matrix.npy").is_file(),
            })
    return {"dir_exists": base.is_dir(), "store_count": len(stores), "stores": stores}


def _table_count(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int | None:
    try:
        return int(conn.execute(sql, params).fetchone()[0])
    except Exception:  # noqa: BLE001
        return None


def _queue_status(db: Any) -> dict[str, Any]:
    with db.get_connection() as conn:
        total = _table_count(conn, "SELECT COUNT(*) FROM extraction_queue")
        pending = _table_count(conn, "SELECT COUNT(*) FROM extraction_queue WHERE terminal=0 AND ignored=0")
        by_outcome = {}
        import contextlib
        with contextlib.suppress(Exception):
            by_outcome = {str(r[0]): int(r[1]) for r in conn.execute(
                "SELECT outcome, COUNT(*) FROM extraction_queue GROUP BY outcome").fetchall()}
    return {"total": total or 0, "retryable_pending": pending or 0, "by_outcome": by_outcome}


def _db_status(db: Any, *, include_paths: bool) -> dict[str, Any]:
    status: dict[str, Any] = {"readable": False}
    if include_paths:
        status["path"] = str(getattr(db, "db_path", "unknown"))
    try:
        db_path = Path(db.db_path)
        status["size_bytes"] = db_path.stat().st_size if db_path.exists() else 0
        with db.get_connection() as conn:
            status["files_total"] = _table_count(conn, "SELECT COUNT(*) FROM files")
            status["files_active"] = _table_count(
                conn, "SELECT COUNT(*) FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'")
            status["files_missing"] = _table_count(
                conn, "SELECT COUNT(*) FROM files WHERE state='MISSING'")
            status["last_indexed_at"] = _table_count(conn, "SELECT MAX(indexed_at) FROM files") and \
                conn.execute("SELECT MAX(indexed_at) FROM files").fetchone()[0]
            try:
                status["last_scan_finished"] = conn.execute(
                    "SELECT MAX(finished_at) FROM scan_runs").fetchone()[0]
            except Exception:  # noqa: BLE001
                status["last_scan_finished"] = None
        status["readable"] = True
    except Exception as exc:  # noqa: BLE001
        status["error"] = type(exc).__name__
    return status


def health_report(db: Any, *, include_paths: bool = False) -> dict[str, Any]:
    config = effective_config(include_paths=include_paths)
    report: dict[str, Any] = {
        "status": "OK",
        "version": app_version(),
        "db": _db_status(db, include_paths=include_paths),
        "schema": check_schema(db),
        "semantic": semantic_status(),
        "ingestion_queue": _queue_status(db),
        "privacy_policy": config["privacy_policy"],
        "ai_mode": config["ai_mode"],
        "api_bind": {"host": config["api_host"], "port": config["api_port"],
                     "loopback_only": config["api_host"] in ("127.0.0.1", "::1", "localhost")},
        "vector_backend": config["vector_backend"],
    }
    try:
        from .doctor import dependency_summary
        report["dependencies"] = dependency_summary()
    except Exception:  # noqa: BLE001
        report["dependencies"] = {}
    if not report["db"].get("readable") or not report["schema"].get("compatible"):
        report["status"] = "DEGRADED"
    return report
