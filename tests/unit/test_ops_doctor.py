"""Doctor diagnostics + health report (M019)."""
from __future__ import annotations

from src.core.database import DatabaseManager
from src.ops.doctor import ERROR, NOT_CONFIGURED, OK, run_doctor
from src.ops.health import health_report


def _db(tmp_path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "files.db")


def test_doctor_returns_classified_checks(tmp_path) -> None:
    report = run_doctor(_db(tmp_path), include_paths=True, probe_network=False)
    assert report["status"] in {OK, "WARN", ERROR}
    names = {c["name"] for c in report["checks"]}
    assert {"db.readable", "db.integrity", "fts", "semantic", "ocr", "pst",
            "privacy_policy", "api_bind"} <= names
    assert all(c["status"] in {OK, "WARN", ERROR, NOT_CONFIGURED} for c in report["checks"])
    # pst is explicitly documented as not configured, never silently "ok"
    pst = next(c for c in report["checks"] if c["name"] == "pst")
    assert pst["status"] == NOT_CONFIGURED


def test_doctor_warns_on_non_loopback_bind(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_API_HOST", "0.0.0.0")
    report = run_doctor(_db(tmp_path), include_paths=False, probe_network=False)
    bind = next(c for c in report["checks"] if c["name"] == "api_bind")
    assert bind["status"] == "WARN" and bind["strong_warning"] is True


def test_doctor_never_leaks_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_API_KEY", "topsecret-doctor")
    report = run_doctor(_db(tmp_path), include_paths=True, probe_network=False)
    assert "topsecret-doctor" not in str(report)


def test_health_report_aggregate_only(tmp_path) -> None:
    db = _db(tmp_path)
    with db.get_connection() as conn:
        conn.execute("INSERT INTO files (id, path, filename, extension, size_bytes, "
                     "modified_at, state, document_kind) VALUES (1, '/private/secret.txt', "
                     "'secret.txt', '.txt', 10, '2024-01-01', 'ACTIVE', 'PHYSICAL_FILE')")
        conn.commit()
    report = health_report(db, include_paths=False)
    assert report["db"]["files_total"] == 1
    assert "/private/secret.txt" not in str(report)  # no private path by default
    assert report["api_bind"]["loopback_only"] is True
    with_paths = health_report(db, include_paths=True)
    assert "/private/secret.txt" in with_paths["db"]["path"] or path_present(with_paths)


def path_present(report: dict) -> bool:
    return "path" in report.get("db", {})
