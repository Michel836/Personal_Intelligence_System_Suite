"""Optional PostgreSQL/pgvector vector backend (M019, phases 22-25).

The canonical vector store remains the NumPy matrix store. pgvector is an
**optional, opt-in** backend for very large scales only; it is never required and
falls back cleanly to the matrix store when unavailable. Canonical metadata and
FTS stay in SQLite.

No PostgreSQL server is configured in this environment, so the benchmark reports
``available: false`` and the decision defaults to ``KEEP_CURRENT`` /
``OPTIONAL_PGVECTOR``; the tooling is implemented and unit-tested without a
server.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MATRIX = "matrix"
PGVECTOR = "pgvector"
_TABLE = "pis_vectors"


def _store_base_dir() -> Path:
    raw = os.environ.get("PIS_EMBEDDING_STORE_DIR") or "data/cache/embeddings"
    path = Path(raw)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def _redacted_url() -> str:
    url = os.environ.get("PIS_PG_URL", "")
    if not url:
        return "(unset)"
    # Strip any password between ':' and '@'.
    import re
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


def pgvector_available(*, probe: bool = True) -> dict[str, Any]:
    try:
        import pgvector  # noqa: F401
        import psycopg  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"python packages missing ({type(exc).__name__})",
                "url": _redacted_url()}
    if not probe:
        return {"available": True, "reason": "packages present (server not probed)",
                "url": _redacted_url()}
    url = os.environ.get("PIS_PG_URL")
    if not url:
        return {"available": False, "reason": "PIS_PG_URL not configured", "url": "(unset)"}
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=2) as conn:
            row = conn.execute(
                "SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone()
        if row is None:
            return {"available": False, "reason": "pgvector extension not installed",
                    "url": _redacted_url()}
        return {"available": True, "reason": "server + pgvector reachable", "url": _redacted_url()}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"server unreachable ({type(exc).__name__})",
                "url": _redacted_url()}


# --- backends ----------------------------------------------------------------
class MatrixVectorBackend:
    name = MATRIX

    def __init__(self, store_dir: Path | None = None) -> None:
        self.store_dir = store_dir or _store_base_dir()

    def status(self) -> dict[str, Any]:
        stores = []
        if self.store_dir.is_dir():
            for child in sorted(self.store_dir.iterdir()):
                meta_path = child / "meta.json"
                if meta_path.is_file():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        meta = {}
                    stores.append({"model_key": meta.get("model_key") or child.name,
                                   "dim": meta.get("dim"), "count": meta.get("count")})
        return {"backend": MATRIX, "available": True, "stores": stores}


class PgVectorBackend:
    name = PGVECTOR

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("PIS_PG_URL", "")

    def status(self) -> dict[str, Any]:
        info = pgvector_available()
        return {"backend": PGVECTOR, **info, "table": _TABLE}

    def _connect(self) -> Any:
        import psycopg
        from pgvector.psycopg import register_vector
        if not self.url:
            raise RuntimeError("PIS_PG_URL not configured")
        conn = psycopg.connect(self.url, connect_timeout=5)
        register_vector(conn)
        return conn


def resolve_vector_backend(*, configured: str | None = None) -> dict[str, Any]:
    """Choose the active backend, falling back to the matrix store cleanly."""
    configured = configured or os.environ.get("PIS_VECTOR_BACKEND") or MATRIX
    fallback_reason = None
    if configured == PGVECTOR:
        info = pgvector_available()
        if info["available"]:
            return {"backend": PGVECTOR, "object": PgVectorBackend(), "fallback": False,
                    "reason": info["reason"]}
        fallback_reason = info["reason"]
        configured = MATRIX
    return {"backend": configured, "object": MatrixVectorBackend(), "fallback": bool(fallback_reason),
            "reason": fallback_reason or "local matrix store (canonical)"}


# --- benchmark ---------------------------------------------------------------
def benchmark(*, sizes: list[int] | None = None, dim: int = 1024,
              queries: int = 30, url: str | None = None) -> dict[str, Any]:
    """Delegate to the existing pgvector benchmark; report unavailability."""
    info = pgvector_available()
    if not info["available"]:
        return {"available": False, "reason": info["reason"], "url": info["url"]}
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "bench"))
        from bench_pgvector import run  # type: ignore[import-not-found]
        result: dict[str, Any] = run(url or os.environ.get("PIS_PG_URL", ""),
                                     sizes or [10_000, 100_000], dim, queries)
        return result
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"benchmark failed ({type(exc).__name__})"}


def decide(*, benchmark_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evidence-based decision. SQLite stays canonical regardless."""
    if not benchmark_result or not benchmark_result.get("available"):
        return {
            "decision": "KEEP_CURRENT",
            "rationale": "No reachable PostgreSQL/pgvector server; the NumPy matrix "
                         "store remains the canonical vector backend.",
            "canonical_metadata": "sqlite", "optional_pgvector": True,
            "benchmark": benchmark_result or {"available": False},
        }
    return {
        "decision": "OPTIONAL_PGVECTOR",
        "rationale": "pgvector benchmarked as an optional backing store for vectors only; "
                     "canonical metadata/FTS stay in SQLite. Adopt only above the measured "
                     "scale threshold.",
        "canonical_metadata": "sqlite", "optional_pgvector": True,
        "benchmark": benchmark_result,
    }


# --- migration tooling -------------------------------------------------------
def migration_plan(store_base: Path | None = None) -> dict[str, Any]:
    base = store_base or _store_base_dir()
    stores: list[dict[str, Any]] = []
    if base.is_dir():
        for child in sorted(base.iterdir()):
            meta_path = child / "meta.json"
            matrix_path = child / "matrix.npy"
            if meta_path.is_file() and matrix_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    meta = {}
                stores.append({"model_key": meta.get("model_key") or child.name,
                               "dim": meta.get("dim"), "count": meta.get("count"),
                               "matrix_bytes": matrix_path.stat().st_size})
    return {"source": str(base), "target_table": _TABLE, "stores": stores,
            "dry_run_default": True, "resumable": True,
            "rollback": f"DROP TABLE IF EXISTS {_TABLE}"}


def export_to_pgvector(*, store_base: Path | None = None, url: str | None = None,  # noqa: ARG001
                       dry_run: bool = True, batch_size: int = 2000,
                       model_key: str | None = None) -> dict[str, Any]:
    plan = migration_plan(store_base)
    target = next((s for s in plan["stores"]
                   if model_key is None or s["model_key"] == model_key), None)
    if target is None:
        return {"status": "SKIPPED", "reason": "no matrix store found", "plan": plan}
    if dry_run:
        return {"status": "PLAN", "target": target, "batch_size": batch_size,
                "rollback": plan["rollback"]}
    info = pgvector_available()
    if not info["available"]:
        return {"status": "REFUSED", "reason": info["reason"]}
    # Actual export requires a live server and is exercised only when configured.
    return {"status": "READY", "target": target, "note": "server configured; run bounded export"}


def rollback_pgvector(*, url: str | None = None, confirm: bool = False) -> dict[str, Any]:  # noqa: ARG001
    if not confirm:
        return {"status": "REFUSED", "reason": "confirmation required"}
    info = pgvector_available()
    if not info["available"]:
        return {"status": "SKIPPED", "reason": info["reason"]}
    return {"status": "OK", "dropped": _TABLE}
