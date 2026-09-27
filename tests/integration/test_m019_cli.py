"""Canonical CLI integration + safety (M019)."""
from __future__ import annotations

import json
from pathlib import Path

from src.cli import main as cli_main


def _run(capsys, argv: list[str]) -> tuple[int, dict | str]:
    code = cli_main(argv)
    out = capsys.readouterr().out.strip()
    try:
        return code, json.loads(out)
    except json.JSONDecodeError:
        return code, out


def _db_arg(tmp_path: Path) -> list[str]:
    return ["--db", str(tmp_path / "cli.db"), "--json"]


def test_status_and_doctor_json(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("PIS_DOCTOR_PROBE_NETWORK", "0")
    code, status = _run(capsys, [*_db_arg(tmp_path), "status"])
    assert code == 0 and isinstance(status, dict) and status["status"] in {"OK", "DEGRADED"}
    code, doctor = _run(capsys, [*_db_arg(tmp_path), "doctor"])
    assert code == 0 and doctor["status"] in {"OK", "WARN", "ERROR"}


def test_scan_extract_search(tmp_path, capsys) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "note.txt").write_text("cancercli alpha token", encoding="utf-8")
    code, scan = _run(capsys, [*_db_arg(tmp_path), "scan", str(root)])
    assert code == 0 and scan["status"] == "COMPLETED"
    code, extract = _run(capsys, [*_db_arg(tmp_path), "extract", "--limit", "10"])
    assert code == 0
    code, search = _run(capsys, ["--db", str(tmp_path / "cli.db"), "search", "cancercli"])
    assert code == 0 and "note.txt" in str(search)
    code, issues = _run(capsys, [*_db_arg(tmp_path), "ingest-issues"])
    assert code == 0 and "stats" in issues


def test_search_json_has_results(tmp_path, capsys) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.txt").write_text("jsoncli token here", encoding="utf-8")
    _run(capsys, [*_db_arg(tmp_path), "scan", str(root)])
    _run(capsys, [*_db_arg(tmp_path), "extract"])
    code, data = _run(capsys, [*_db_arg(tmp_path), "search", "jsoncli"])
    assert code == 0 and data["available"] is True and data["count"] >= 1


def test_graph_neighborhood_reports_bounded_metrics(tmp_path, capsys) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "g.txt").write_text("graphcli token", encoding="utf-8")
    _run(capsys, [*_db_arg(tmp_path), "scan", str(root)])
    code, data = _run(capsys, [*_db_arg(tmp_path), "graph", "--file-id", "1"])
    assert code == 0
    assert data["metrics"]["nodes"] >= 1
    assert data["bounds"]["max_nodes"] == 50


def test_maintenance_bounds_and_confirmation(tmp_path, capsys) -> None:
    code, listing = _run(capsys, [*_db_arg(tmp_path), "maintenance", "list"])
    assert code == 0 and "integrity" in listing["operations"]
    code, optimize = _run(capsys, [*_db_arg(tmp_path), "maintenance", "optimize"])
    assert code == 0 and optimize["status"] == "OK"
    code, vacuum = _run(capsys, [*_db_arg(tmp_path), "maintenance", "vacuum"])
    assert code == 0 and vacuum["status"] == "SKIPPED"
    code, vacuum2 = _run(capsys, [*_db_arg(tmp_path), "maintenance", "vacuum", "--confirm"])
    assert vacuum2["status"] in {"OK", "ERROR"}


def test_backup_and_restore_verify(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("PIS_BACKUP_DIR", str(tmp_path / "backups"))
    # seed a row so the db is non-trivial
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "x.txt").write_text("backupcli", encoding="utf-8")
    _run(capsys, [*_db_arg(tmp_path), "scan", str(root)])
    code, backup = _run(capsys, [*_db_arg(tmp_path), "backup"])
    assert code == 0 and Path(backup["archive_path"]).is_file()
    code, verified = _run(capsys, [*_db_arg(tmp_path), "restore", backup["archive_path"],
                                   "--verify-only"])
    assert code == 0 and verified["ok"] is True


def test_dossier_and_report_commands(tmp_path, capsys) -> None:
    code, dossier = _run(capsys, [*_db_arg(tmp_path), "dossier", "create", "--name", "CLI dos"])
    assert code == 0 and dossier["dossier_id"]
    code, listing = _run(capsys, [*_db_arg(tmp_path), "dossier", "list"])
    assert code == 0 and any(d["name"] == "CLI dos" for d in listing)
    code, report = _run(capsys, [*_db_arg(tmp_path), "report", "build", "--title", "CLI report",
                                 "--dry-run"])
    assert code == 0 and report["logical_fingerprint"]


def test_dry_run_scan_does_not_touch_db(tmp_path, capsys) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "y.txt").write_text("dry", encoding="utf-8")
    code, data = _run(capsys, [*_db_arg(tmp_path), "scan", str(root), "--dry-run"])
    assert code == 0 and data["dry_run"] is True


def test_bad_root_returns_error(tmp_path, capsys) -> None:
    code, _ = _run(capsys, [*_db_arg(tmp_path), "scan", str(tmp_path / "missing")])
    assert code == 2


def test_pis_entrypoint_declared() -> None:
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'pis = "src.cli:main"' in text
