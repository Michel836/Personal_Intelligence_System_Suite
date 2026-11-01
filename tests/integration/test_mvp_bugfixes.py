"""Regression tests for the four MVP bugfixes (Week 4, point 9)."""
from __future__ import annotations

import json
from pathlib import Path

from src.cli import main as cli_main


def _scan_corpus(tmp_path: Path, monkeypatch) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "facture.txt").write_text(
        "Facture ACME 1250 EUR, contact jean@example.com", encoding="utf-8"
    )
    monkeypatch.setenv("PIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "data" / "indexes" / "files.db"))
    monkeypatch.setenv("PIS_EXPORT_DIR", str(tmp_path / "exports"))
    assert cli_main(["--json", "scan", str(corpus)]) == 0
    assert cli_main(["--json", "extract", "--limit", "10"]) == 0
    return corpus


def test_report_formats_are_case_insensitive(tmp_path, monkeypatch, capsys) -> None:
    _scan_corpus(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cli_main([
        "--json", "report", "build", "--kind", "SEARCH",
        "--query", json.dumps({"query": "facture"}), "--formats", "json,html",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    formats = {artifact["format"] for artifact in payload["artifacts"]}
    assert formats == {"JSON", "HTML"}


def test_report_unknown_format_is_a_usage_error(tmp_path, monkeypatch, capsys) -> None:
    _scan_corpus(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cli_main([
        "--json", "report", "build", "--kind", "SEARCH", "--formats", "xml",
    ]) == 2
    assert "unknown report format" in capsys.readouterr().err


def test_semantic_consistency_is_scoped_to_the_database(tmp_path) -> None:
    """A fresh DB never claims inconsistency against an unrelated global store."""
    from src.core.database import DatabaseManager
    from src.ops.maintenance import MaintenanceService

    db = DatabaseManager(tmp_path / "trial.db")
    result = MaintenanceService(db).semantic_consistency()
    assert result["status"] == "OK"
    assert result["details"]["consistent"] is True
    assert result["details"]["store_checked"] is False


def test_semantic_consistency_checks_the_bound_store(tmp_path, monkeypatch) -> None:
    from src.core.database import DatabaseManager
    from src.ops.maintenance import MaintenanceService

    store_dir = tmp_path / "store"
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(store_dir))
    db = DatabaseManager(tmp_path / "bound.db")
    db.set_semantic_store_dir(str(store_dir))
    result = MaintenanceService(db).semantic_consistency()
    assert result["details"]["store_checked"] is True
    assert result["details"]["store_dir"] == str(store_dir)


def test_canonical_app_has_no_dead_modern_link() -> None:
    source = (Path(__file__).resolve().parents[2] / "src" / "ui" / "app.py").read_text(
        encoding="utf-8"
    )
    assert "modern_app" not in source
    assert "Version Moderne" not in source


def test_cli_json_meta_always_exposes_the_database(tmp_path, monkeypatch, capsys) -> None:
    _scan_corpus(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cli_main(["--json", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["_meta"]["db"].endswith("indexes/files.db")
    assert "semantic_coverage" in payload
    assert "extraction_coverage" in payload


def test_status_embeds_semantic_coverage_in_human_output(tmp_path, monkeypatch, capsys) -> None:
    _scan_corpus(tmp_path, monkeypatch)
    capsys.readouterr()
    assert cli_main(["status"]) == 0
    captured = capsys.readouterr()
    assert "semantic=" in captured.out
    assert "db:" in captured.err
