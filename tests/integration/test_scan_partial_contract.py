"""Safe partial-scan contract (Week 1, point 1).

A scan must never fail just because *some* subtree is unreadable, and it must
never infer deletion for paths that were not exhaustively traversed. These
tests pin both halves of that contract:

* ``ignore_errors`` -> ``COMPLETED_WITH_WARNINGS`` with per-subtree evidence;
* strict mode still fails closed (``FAILED``) and never reconciles;
* reconciliation skips only the unscanned scopes.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.scanner.fast_engine import FastScannerEngine


def _can_make_unreadable() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() != 0


pytestmark = pytest.mark.skipif(
    not _can_make_unreadable(),
    reason="permission-denied semantics require a non-root user",
)


def _make_corpus(root: Path) -> Path:
    corpus = root / "corpus"
    (corpus / "ok").mkdir(parents=True)
    (corpus / "ok" / "a.txt").write_text("alpha", encoding="utf-8")
    for name in ("locked1", "locked2", "locked3"):
        (corpus / name).mkdir()
        (corpus / name / f"{name}.txt").write_text(name, encoding="utf-8")
    return corpus


def _lock(path: Path) -> None:
    os.chmod(path, 0o000)


def _unlock(path: Path) -> None:
    os.chmod(path, 0o755)


def _states(db: DatabaseManager) -> dict[str, str]:
    with db.get_connection() as conn:
        return {
            row["path"]: row["state"]
            for row in conn.execute("SELECT path, state FROM files")
        }


def test_partial_scan_completes_with_warnings_and_never_reconciles_unreadable(
    tmp_path: Path,
) -> None:
    corpus = _make_corpus(tmp_path)
    db = DatabaseManager(tmp_path / "index.db")
    service = ScanService(db)

    first = service.run(ScanRequest(root=corpus))
    assert first.status == "COMPLETED"
    assert first.files_seen == 4

    locked = [corpus / name for name in ("locked1", "locked2", "locked3")]
    for path in locked:
        _lock(path)
    try:
        (corpus / "ok" / "later.txt").write_text("later", encoding="utf-8")
        result = service.run(ScanRequest(root=corpus, ignore_errors=True))
    finally:
        for path in locked:
            _unlock(path)

    assert result.status == "COMPLETED_WITH_WARNINGS"
    assert result.files_errors == 3
    assert result.unscanned_scopes == 3
    assert result.reconciled is True
    assert result.files_upserted == 2  # a.txt + later.txt

    states = _states(db)
    for name in ("locked1", "locked2", "locked3"):
        assert states[str(corpus / name / f"{name}.txt")] == "ACTIVE"
    assert states[str(corpus / "ok" / "later.txt")] == "ACTIVE"

    scopes = db.scan_scopes(result.run_id)
    assert {scope["kind"] for scope in scopes} == {"directory"}
    assert {scope["path"] for scope in scopes} == {str(path) for path in locked}


def test_strict_scan_fails_closed_and_does_not_reconcile(tmp_path: Path) -> None:
    corpus = _make_corpus(tmp_path)
    db = DatabaseManager(tmp_path / "index.db")
    service = ScanService(db)
    assert service.run(ScanRequest(root=corpus)).status == "COMPLETED"

    locked = corpus / "locked2"
    _lock(locked)
    try:
        result = service.run(ScanRequest(root=corpus, ignore_errors=False))
    finally:
        _unlock(locked)

    assert result.status == "FAILED"
    assert "Permission denied" in (result.error or "")
    # Nothing was reconciled: every previously indexed file is still ACTIVE.
    assert set(_states(db).values()) == {"ACTIVE"}
    assert db.scan_scopes(result.run_id)  # evidence is still recorded


def test_excluded_subtree_is_not_reconciled_but_deleted_file_is(tmp_path: Path) -> None:
    corpus = _make_corpus(tmp_path)
    db = DatabaseManager(tmp_path / "index.db")
    service = ScanService(db)
    assert service.run(ScanRequest(root=corpus)).status == "COMPLETED"

    # A file in a fully traversed subtree is deleted -> MISSING.
    (corpus / "ok" / "a.txt").unlink()
    result = service.run(
        ScanRequest(root=corpus, ignore_errors=True, exclude_dirs=("locked1",))
    )

    assert result.status == "COMPLETED_WITH_WARNINGS"
    assert result.unscanned_scopes == 1
    states = _states(db)
    assert states[str(corpus / "ok" / "a.txt")] == "MISSING"
    assert states[str(corpus / "locked1" / "locked1.txt")] == "ACTIVE"
    assert states[str(corpus / "locked2" / "locked2.txt")] == "ACTIVE"

    scopes = db.scan_scopes(result.run_id)
    assert scopes == [
        {
            "path": str(corpus / "locked1"),
            "kind": "excluded",
            "message": "user exclusion",
        }
    ]


def test_exclude_path_protects_a_specific_tree(tmp_path: Path) -> None:
    corpus = _make_corpus(tmp_path)
    db = DatabaseManager(tmp_path / "index.db")
    service = ScanService(db)
    assert service.run(ScanRequest(root=corpus)).status == "COMPLETED"

    (corpus / "locked3" / "locked3.txt").unlink()
    result = service.run(
        ScanRequest(root=corpus, exclude_paths=(str(corpus / "locked3"),))
    )
    assert result.status == "COMPLETED_WITH_WARNINGS"
    assert _states(db)[str(corpus / "locked3" / "locked3.txt")] == "ACTIVE"


def test_scanner_exclusion_patterns_support_globs(tmp_path: Path) -> None:
    corpus = _make_corpus(tmp_path)
    (corpus / "ok" / "skip.tmp").write_text("x", encoding="utf-8")
    engine = FastScannerEngine(exclude_dirs=("*.tmp", "locked?"))
    found = [info.path.name for info in engine.scan_paths([corpus])]
    assert "skip.tmp" not in found
    assert not any(name.startswith("locked") for name in found)
    assert "a.txt" in found


def test_cli_scan_exit_codes(tmp_path: Path, capsys, monkeypatch) -> None:
    from src.cli import main as cli_main

    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "cli.db"))
    corpus = _make_corpus(tmp_path)

    assert cli_main(["--json", "scan", str(corpus)]) == 0
    capsys.readouterr()

    locked = corpus / "locked1"
    _lock(locked)
    try:
        assert cli_main(["--json", "scan", str(corpus)]) == 3
        capsys.readouterr()
        assert cli_main(["--json", "scan", str(corpus), "--strict"]) == 2
        captured = capsys.readouterr()
    finally:
        _unlock(locked)

    assert '"status": "FAILED"' in captured.out


def test_env_exclusions_are_honoured(tmp_path: Path, monkeypatch) -> None:
    from src.cli import main as cli_main

    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "env.db"))
    monkeypatch.setenv("PIS_SCAN_EXCLUDE_DIRS", "locked2")
    corpus = _make_corpus(tmp_path)
    assert cli_main(["--json", "scan", str(corpus)]) == 3  # excluded scope warning
    states = _states(DatabaseManager(tmp_path / "env.db"))
    assert str(corpus / "locked2" / "locked2.txt") not in states
    assert str(corpus / "locked1" / "locked1.txt") in states


def test_scope_overflow_completes_without_reconciliation(tmp_path: Path, monkeypatch) -> None:
    """More unscanned scopes than the safety cap must not fail the whole scan.

    The indexed metadata is kept, the run ends COMPLETED_WITH_WARNINGS, and
    reconciliation is skipped entirely (no file is ever marked MISSING).
    """
    corpus = _make_corpus(tmp_path)
    db = DatabaseManager(tmp_path / "index.db")
    service = ScanService(db)
    assert service.run(ScanRequest(root=corpus)).status == "COMPLETED"

    # Force the overflow branch with a tiny cap.
    monkeypatch.setattr("src.scanner.fast_engine.MAX_RECORDED_ERRORS", 2)
    locked = [corpus / name for name in ("locked1", "locked2", "locked3")]
    for path in locked:
        _lock(path)
    try:
        (corpus / "ok" / "later.txt").write_text("later", encoding="utf-8")
        result = service.run(ScanRequest(root=corpus, ignore_errors=True))
    finally:
        for path in locked:
            _unlock(path)

    assert result.status == "COMPLETED_WITH_WARNINGS"
    assert result.files_errors == 3
    assert result.reconciled is False
    assert any("reconciliation skipped" in warning for warning in result.warnings)
    states = _states(db)
    for name in ("locked1", "locked2", "locked3"):
        assert states[str(corpus / name / f"{name}.txt")] == "ACTIVE"
    assert states[str(corpus / "ok" / "later.txt")] == "ACTIVE"


def test_scope_overflow_strict_still_fails(tmp_path: Path, monkeypatch) -> None:
    corpus = _make_corpus(tmp_path)
    db = DatabaseManager(tmp_path / "index.db")
    service = ScanService(db)
    assert service.run(ScanRequest(root=corpus)).status == "COMPLETED"

    monkeypatch.setattr("src.scanner.fast_engine.MAX_RECORDED_ERRORS", 2)
    locked = [corpus / name for name in ("locked1", "locked2", "locked3")]
    for path in locked:
        _lock(path)
    try:
        result = service.run(ScanRequest(root=corpus, ignore_errors=False))
    finally:
        for path in locked:
            _unlock(path)

    assert result.status == "FAILED"
    assert set(_states(db).values()) == {"ACTIVE"}
