"""Canonical doctor / diagnostics service (M019, phase 10).

Every check returns one of ``OK`` / ``WARN`` / ``ERROR`` / ``NOT_CONFIGURED``.
Checks are bounded: the integrity check is skipped (WARN) on large databases and
must be run explicitly via ``pis maintenance integrity``. Network probes (Ollama)
are short and can be disabled with ``PIS_DOCTOR_PROBE_NETWORK=0``.
"""
from __future__ import annotations

import importlib
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from .config import effective_config
from .schema import check_schema
from .version import app_version

OK = "OK"
WARN = "WARN"
ERROR = "ERROR"
NOT_CONFIGURED = "NOT_CONFIGURED"

_INTEGRITY_MAX_MB = int(os.environ.get("PIS_DOCTOR_INTEGRITY_MAX_MB", "256"))

#: Optional tools and what they unlock.
TOOLS: dict[str, str] = {
    "tesseract": "OCR (opt-in)",
    "7z": "CHM + 7z archives",
    "unar": "RAR archives",
    "unrar": "RAR archives",
    "libreoffice": "legacy Office, RTF, PDF export",
    "pandoc": "document conversion",
    "google-chrome": "PDF export fallback",
    "readpst": "PST/OST email (optional)",
}
#: Optional Python modules.
MODULES: dict[str, str] = {
    "PIL": "image/OCR preprocessing",
    "PyPDF2": "PDF text + validation",
    "pytesseract": "OCR bindings",
    "psycopg": "optional PostgreSQL/pgvector",
    "pgvector": "optional pgvector types",
    "starlette": "local REST API",
    "uvicorn": "local REST API server",
    "docx": "DOCX handling",
    "openpyxl": "XLSX handling",
}


def _which(name: str) -> str | None:
    return shutil.which(name)


def tool_status() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, purpose in TOOLS.items():
        path = _which(name)
        out[name] = {"available": path is not None, "purpose": purpose}
    return out


def module_status() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, purpose in MODULES.items():
        try:
            importlib.import_module(name)
            available = True
        except Exception:  # noqa: BLE001
            available = False
        out[name] = {"available": available, "purpose": purpose}
    return out


def dependency_summary() -> dict[str, Any]:
    tools = tool_status()
    mods = module_status()
    return {
        "tools_available": sorted(n for n, v in tools.items() if v["available"]),
        "tools_missing": sorted(n for n, v in tools.items() if not v["available"]),
        "modules_available": sorted(n for n, v in mods.items() if v["available"]),
        "modules_missing": sorted(n for n, v in mods.items() if not v["available"]),
    }


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, **extra}


# --- individual checks -------------------------------------------------------
def _db_checks(db: Any, *, deep: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    db_path = Path(getattr(db, "db_path", ""))
    try:
        with db.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        checks.append(_check("db.readable", OK, "connection established"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("db.readable", ERROR, type(exc).__name__))
        return checks
    # Writable probe (rolled back — never persists a change).
    try:
        with db.get_connection() as conn:
            conn.execute("BEGIN")
            conn.execute("CREATE TABLE IF NOT EXISTS _pis_write_probe(x INTEGER)")
            conn.execute("DROP TABLE _pis_write_probe")
            conn.rollback()
        checks.append(_check("db.writable", OK, "write probe rolled back"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("db.writable", ERROR, type(exc).__name__))
    size_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0
    if deep or size_mb <= _INTEGRITY_MAX_MB:
        try:
            with db.get_connection() as conn:
                result = conn.execute("PRAGMA quick_check").fetchone()[0]
            status = OK if result == "ok" else ERROR
            checks.append(_check("db.integrity", status, str(result)))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check("db.integrity", ERROR, type(exc).__name__))
    else:
        checks.append(_check("db.integrity", WARN,
                             f"skipped for {size_mb:.0f} MB db; run 'pis maintenance integrity'"))
    checks.append(_check("db.schema", OK if check_schema(db)["compatible"] else WARN,
                         ", ".join(check_schema(db)["notes"]) or "compatible"))
    return checks


def _fts_check(db: Any) -> dict[str, Any]:
    try:
        with db.get_connection() as conn:
            files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            indexed = conn.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0]
        if files == indexed:
            return _check("fts", OK, f"{indexed} rows indexed")
        return _check("fts", WARN, f"files={files} indexed={indexed} (run 'pis maintenance fts-rebuild')")
    except Exception as exc:  # noqa: BLE001
        return _check("fts", ERROR, type(exc).__name__)


def _semantic_check() -> dict[str, Any]:
    from .health import semantic_status
    status = semantic_status()
    if not status["dir_exists"] or status["store_count"] == 0:
        return _check("semantic", NOT_CONFIGURED, "no embedding store present")
    bad = [s for s in status["stores"] if not s.get("matrix_present") or not s.get("dim")]
    if bad:
        return _check("semantic", WARN, f"{len(bad)} store(s) missing matrix/dim")
    total = sum(int(s.get("count") or 0) for s in status["stores"])
    return _check("semantic", OK, f"{status['store_count']} store(s), {total} vectors")


def _network_checks(*, probe: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if not probe:
        checks.append(_check("ollama", NOT_CONFIGURED, "network probe disabled"))
        return checks
    url = os.environ.get("PIS_OLLAMA_URL") or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/tags", timeout=1.5) as resp:  # noqa: S310 - loopback config
            ok = resp.status == 200
        checks.append(_check("ollama", OK if ok else WARN, f"{url} reachable"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("ollama", WARN, f"unreachable ({type(exc).__name__}) — optional"))
    return checks


def _space_check(name: str, path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        status = OK if free_gb >= 1 else WARN
        return _check(name, status, f"{free_gb:.1f} GB free")
    except Exception as exc:  # noqa: BLE001
        return _check(name, ERROR, type(exc).__name__)


def _dir_writable_check(name: str, path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".pis_probe_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return _check(name, OK, "exists and writable")
    except Exception as exc:  # noqa: BLE001
        return _check(name, ERROR, type(exc).__name__)


def run_doctor(db: Any, *, deep: bool = False, include_paths: bool = False,
               probe_network: bool | None = None) -> dict[str, Any]:
    if probe_network is None:
        probe_network = os.environ.get("PIS_DOCTOR_PROBE_NETWORK", "1") != "0"
    config = effective_config(include_paths=True)
    checks: list[dict[str, Any]] = []
    checks.extend(_db_checks(db, deep=deep))
    checks.append(_fts_check(db))
    checks.append(_semantic_check())
    checks.extend(_network_checks(probe=probe_network))

    tools = tool_status()
    checks.append(_check("ocr", OK if tools["tesseract"]["available"] else WARN,
                         "tesseract present" if tools["tesseract"]["available"]
                         else "tesseract missing (OCR opt-in)"))
    libs = module_status()
    checks.append(_check("api_backend",
                         OK if libs["starlette"]["available"] and libs["uvicorn"]["available"]
                         else NOT_CONFIGURED,
                         "starlette+uvicorn present" if libs["starlette"]["available"]
                         else "install starlette+uvicorn for the local API"))
    checks.append(_check("pst", NOT_CONFIGURED,
                         "readpst/pypff absent — PST/OST documented as unsupported"))
    checks.append(_check("legacy_office", OK if tools["libreoffice"]["available"] else WARN,
                         "libreoffice present" if tools["libreoffice"]["available"]
                         else "libreoffice missing"))
    checks.append(_check("pdf_provider",
                         OK if (tools["libreoffice"]["available"] or tools["google-chrome"]["available"]
                                or libs["PyPDF2"]["available"]) else WARN,
                         "a local PDF provider is present"))

    if include_paths:
        paths = config["paths"]
        checks.append(_dir_writable_check("export_dir", Path(paths["export_dir"])))
        checks.append(_dir_writable_check("backup_dir", Path(paths["backup_dir"])))
        checks.append(_space_check("disk_repo", Path(paths["repo_root"])))
        checks.append(_space_check("disk_temp", Path(paths["temp_dir"])))
        checks.append(_check("permissions_db",
                             OK if os.access(paths["db"], os.W_OK) or not Path(paths["db"]).exists()
                             else WARN,
                             "db writable" if os.access(paths["db"], os.W_OK) else "db not writable"))

    policy = config["privacy_policy"]
    checks.append(_check("privacy_policy", OK if policy == "never" else WARN,
                         f"PIS_REMOTE_CONTENT_POLICY={policy}"))
    host = config["api_host"]
    loopback = host in ("127.0.0.1", "::1", "localhost")
    checks.append(_check("api_bind", OK if loopback else WARN,
                         f"host={host}" + ("" if loopback else " (non-loopback requires explicit opt-in + TLS/auth)"),
                         strong_warning=not loopback))

    overall = OK
    if any(c["status"] == ERROR for c in checks):
        overall = ERROR
    elif any(c["status"] == WARN for c in checks):
        overall = WARN
    return {"status": overall, "version": app_version(), "checks": checks,
            "dependencies": {"tools": tools, "modules": libs},
            "config": config}
