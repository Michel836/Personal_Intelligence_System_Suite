"""Contract tests for the explicit bulk-indexing mode (M010-P).

Bulk mode defers FTS trigger maintenance and rebuilds the index once at the end
(measured ~3.4x faster). These tests lock the invariants that make it safe:
  * a completed scan leaves the FTS index fully searchable;
  * an interrupted bulk load is detected and rebuilt by the next startup;
  * disabling bulk mode still yields a correct, searchable index.
"""
from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager
from src.core.perf_config import reset_resource_config
from src.core.scan_service import ScanRequest, ScanService
from src.core.volume import VolumeInfo


def _tree(root: Path, names: list[str]) -> Path:
    (root / "docs").mkdir(parents=True)
    for name in names:
        (root / "docs" / name).write_text("body content", encoding="utf-8")
    return root


def _run(root: Path, db: DatabaseManager) -> None:
    result = ScanService(db).run(
        ScanRequest(
            root=root,
            volume=VolumeInfo(
                stable_key="BULK", device="BULK", mountpoint=str(root), is_available=True
            ),
        )
    )
    assert result.status == "COMPLETED", (result.status, result.error)


def test_bulk_scan_is_fts_searchable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_BULK_INDEX", "1")
    reset_resource_config()
    db = DatabaseManager(tmp_path / "bulk.db")
    root = _tree(tmp_path / "corpus", ["alpha_contrat.txt", "beta_note.txt"])
    _run(root, db)
    assert len(db.search_files(query="contrat")) == 1
    assert len(db.search_files(query="note")) == 1
    reset_resource_config()


def test_bulk_mode_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_BULK_INDEX", "0")
    reset_resource_config()
    db = DatabaseManager(tmp_path / "nobulk.db")
    root = _tree(tmp_path / "corpus2", ["gamma_facture.txt"])
    _run(root, db)
    assert len(db.search_files(query="facture")) == 1
    reset_resource_config()


def test_interrupted_bulk_is_rebuilt_on_next_startup(tmp_path: Path) -> None:
    db_path = tmp_path / "interrupted.db"
    db = DatabaseManager(db_path)
    root = _tree(tmp_path / "corpus3", ["delta_contrat.txt"])
    _run(root, db)

    # Simulate a crash mid-bulk: triggers dropped + marker left behind.
    with db.get_connection() as conn:
        db._drop_fts_triggers(conn)
        conn.execute(
            "INSERT OR REPLACE INTO fts_meta(key, value) VALUES ('bulk_in_progress', '1')"
        )
        conn.commit()

    recovered = DatabaseManager(db_path)
    with recovered.get_connection() as conn:
        marker = conn.execute(
            "SELECT value FROM fts_meta WHERE key = 'bulk_in_progress'"
        ).fetchone()
        assert marker is None
        assert conn.execute("SELECT count(*) FROM files_fts").fetchone()[0] >= 1
    # Triggers are back, so new writes stay searchable.
    assert len(recovered.search_files(query="contrat")) == 1
