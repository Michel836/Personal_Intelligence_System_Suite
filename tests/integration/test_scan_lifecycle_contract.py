"""Contract tests for the volume-aware scan lifecycle (M005A.2-A.4).

Covers volume identity, scan-run statuses, last-seen stamping, reversible
MISSING reconciliation with failed/cancelled/unavailable protection, root
scoping, legacy migration preservation, and HIGH-confidence inode rename/move
association.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.core.volume import VolumeInfo
from src.scanner.fast_engine import FastScannerEngine


def _vol(key: str, mount: Path, *, available: bool = True) -> VolumeInfo:
    return VolumeInfo(
        stable_key=key,
        device=key,
        fs_type="testfs",
        mountpoint=str(mount),
        is_available=available,
    )


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "life.db")


def _scan(db: DatabaseManager, root: Path, volume: VolumeInfo):
    info = db.begin_scan(root, volume=volume)
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([root])))
    return info, db.complete_scan(info["run_id"])


def _state(db: DatabaseManager) -> dict[str, str]:
    return {
        row["filename"]: row["state"]
        for row in db.search_files(limit=1000, include_missing=True)
    }


# --- M005A.2: volume + scan-run foundation --------------------------------
def test_new_volume_registered(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    info, rec = _scan(db, root, _vol("V1", tmp_path))
    assert rec["missing"] == 0
    with db.get_connection() as conn:
        volumes = conn.execute("SELECT * FROM volumes").fetchall()
    assert len(volumes) == 1
    assert volumes[0]["stable_key"] == "V1"
    assert volumes[0]["is_available"] == 1


def test_known_volume_reused(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    _scan(db, root, _vol("V1", tmp_path))
    _scan(db, root, _vol("V1", tmp_path))
    with db.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM volumes").fetchone()[0] == 1


def test_same_volume_new_mountpoint(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    first, _ = _scan(db, root, _vol("V1", tmp_path / "m1"))
    second, _ = _scan(db, root, _vol("V1", tmp_path / "m2"))
    assert first["volume_id"] == second["volume_id"]
    with db.get_connection() as conn:
        mount = conn.execute(
            "SELECT mountpoint FROM volumes WHERE id = ?", (first["volume_id"],)
        ).fetchone()[0]
    assert mount.endswith("m2")


def test_multiple_roots_same_volume(db: DatabaseManager, tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "a.txt").write_text("a", encoding="utf-8")
    (root_b / "b.txt").write_text("b", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root_a, volume)
    _scan(db, root_b, volume)
    assert len(db.search_files(limit=100)) == 2


def test_run_statuses(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    volume = _vol("V1", tmp_path)

    completed = db.begin_scan(root, volume=volume)
    with db.get_connection() as conn:
        assert conn.execute(
            "SELECT status FROM scan_runs WHERE id = ?", (completed["run_id"],)
        ).fetchone()[0] == "RUNNING"
    db.record_scan_files(completed["run_id"], list(FastScannerEngine().scan_paths([root])))
    db.complete_scan(completed["run_id"])

    failed = db.begin_scan(tmp_path / "f", volume=volume)
    db.fail_scan(failed["run_id"], "boom")
    cancelled = db.begin_scan(tmp_path / "c", volume=volume)
    db.cancel_scan(cancelled["run_id"])

    with db.get_connection() as conn:
        statuses = {
            row["id"]: row["status"]
            for row in conn.execute("SELECT id, status FROM scan_runs")
        }
    assert statuses[completed["run_id"]] == "COMPLETED"
    assert statuses[failed["run_id"]] == "FAILED"
    assert statuses[cancelled["run_id"]] == "CANCELLED"


def test_last_seen_updates(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    second, _ = _scan(db, root, volume)
    with db.get_connection() as conn:
        assert conn.execute("SELECT last_seen_scan_id FROM files").fetchone()[0] == second["run_id"]


def test_legacy_rows_preserved_on_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL, extension TEXT, size_bytes INTEGER,
            file_type TEXT, priority TEXT, created_at TEXT, modified_at TEXT,
            content_text TEXT, content_extracted BOOLEAN DEFAULT 0, metadata TEXT,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP, checksum TEXT,
            parent_dir TEXT, depth INTEGER)"""
    )
    conn.execute(
        """INSERT INTO files
           (path, filename, extension, size_bytes, file_type, priority,
            created_at, modified_at, content_text)
           VALUES ('/x/a.txt', 'a.txt', '.txt', 1, 'document', 'medium',
                   '2024-01-01', '2024-01-01', 'legacy content')"""
    )
    conn.commit()
    conn.close()

    migrated = DatabaseManager(path)
    rows = migrated.search_files(limit=100)
    assert len(rows) == 1
    assert rows[0]["content_text"] == "legacy content"
    assert rows[0]["state"] == "ACTIVE"      # backfilled, not deleted
    assert rows[0]["volume_id"] is None      # never in a scan run


def test_unavailable_volume_refuses_reconcile(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("a", encoding="utf-8")
    _scan(db, root, _vol("V1", tmp_path))
    target.unlink()

    info = db.begin_scan(root, volume=_vol("V1", tmp_path, available=False))
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([root])))
    with pytest.raises(ValueError):
        db.complete_scan(info["run_id"])
    assert _state(db)["a.txt"] == "ACTIVE"


def test_root_normalization_and_overlap(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("a", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    info = db.begin_scan(root, volume=volume)
    try:
        with pytest.raises(ValueError):
            db.begin_scan(root / "sub", volume=volume)
        with pytest.raises(ValueError):
            db.begin_scan(root / ".", volume=volume)
    finally:
        db.cancel_scan(info["run_id"])


# --- M005A.3: reversible reconciliation -----------------------------------
def test_delete_then_completed_marks_missing(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    keep = root / "keep.txt"
    gone = root / "gone.txt"
    keep.write_text("keep", encoding="utf-8")
    gone.write_text("gone", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    gone.unlink()

    _, rec = _scan(db, root, volume)
    assert rec["missing"] == 1
    assert [r["filename"] for r in db.search_files(limit=100)] == ["keep.txt"]
    assert _state(db)["gone.txt"] == "MISSING"
    assert "gone.txt" in [r["filename"] for r in db.search_files(limit=100, include_missing=True)]


def test_cancelled_and_failed_scans_do_not_reconcile(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("a", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    target.unlink()

    cancelled = db.begin_scan(root, volume=volume)
    db.record_scan_files(cancelled["run_id"], list(FastScannerEngine().scan_paths([root])))
    db.cancel_scan(cancelled["run_id"])
    assert _state(db)["a.txt"] == "ACTIVE"

    failed = db.begin_scan(root, volume=volume)
    db.fail_scan(failed["run_id"], "crash")
    assert _state(db)["a.txt"] == "ACTIVE"


def test_partial_root_scope_does_not_touch_other_root(db: DatabaseManager, tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "a.txt").write_text("a", encoding="utf-8")
    (root_b / "b.txt").write_text("b", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root_a, volume)
    _scan(db, root_b, volume)

    (root_b / "b.txt").unlink()
    _scan(db, root_a, volume)  # only reconciles root_a

    assert _state(db)["b.txt"] == "ACTIVE"  # untouched, different scope


def test_reconnect_restores_active_and_content(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("a", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    file_id = db.search_files()[0]["id"]
    db.update_content(file_id, "important extracted text")

    target.unlink()
    _scan(db, root, volume)
    assert _state(db)["a.txt"] == "MISSING"

    target.write_text("a", encoding="utf-8")
    _scan(db, root, volume)
    row = db.search_files()[0]
    assert row["state"] == "ACTIVE"
    assert row["id"] == file_id
    assert row["content_text"] == "important extracted text"
    assert len(db.search_files(query="important")) == 1


def test_reconciliation_is_idempotent(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("a", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    target.unlink()
    _, first = _scan(db, root, volume)
    assert first["missing"] == 1
    _, second = _scan(db, root, volume)
    assert second["missing"] == 0
    assert _state(db)["a.txt"] == "MISSING"


# --- M005A.4: filesystem identity / rename-move ---------------------------
def _content_and_id(db: DatabaseManager, name: str):
    row = [r for r in db.search_files(limit=100) if r["filename"] == name][0]
    return row["id"], row["content_text"]


def test_same_volume_rename_preserves_identity(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    source = root / "a_alpha.txt"
    source.write_text("rename body", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    file_id = db.search_files()[0]["id"]
    db.update_content(file_id, "preserved content")

    source.rename(root / "b_beta.txt")
    _, rec = _scan(db, root, volume)

    assert rec["renamed"] == 1
    assert rec["missing"] == 0
    rows = db.search_files(limit=100)
    assert len(rows) == 1
    assert rows[0]["id"] == file_id
    assert rows[0]["filename"] == "b_beta.txt"
    assert rows[0]["content_text"] == "preserved content"
    assert db.search_files(query="alpha") == []
    assert [r["filename"] for r in db.search_files(query="beta")] == ["b_beta.txt"]


def test_same_volume_move_preserves_identity(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    (root / "one").mkdir(parents=True)
    (root / "two").mkdir()
    source = root / "one" / "m.txt"
    source.write_text("move body", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    file_id = db.search_files()[0]["id"]

    shutil.move(str(source), str(root / "two" / "m.txt"))
    _, rec = _scan(db, root, volume)

    assert rec["renamed"] == 1
    row = db.search_files()[0]
    assert row["id"] == file_id
    assert row["path"].endswith("two/m.txt")
    assert _state(db) == {"m.txt": "ACTIVE"}


def test_cross_volume_move_is_not_merged(db: DatabaseManager, tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    source = root_a / "x.txt"
    source.write_text("cross body", encoding="utf-8")
    vol_a = _vol("VA", tmp_path)
    vol_b = _vol("VB", tmp_path)

    _scan(db, root_a, vol_a)
    source.unlink()
    _scan(db, root_a, vol_a)  # marked MISSING
    (root_b / "x.txt").write_text("cross body", encoding="utf-8")
    _scan(db, root_b, vol_b)

    states = {(r["filename"], r["state"]) for r in db.search_files(limit=100, include_missing=True)}
    assert ("x.txt", "MISSING") in states
    assert ("x.txt", "ACTIVE") in states


def test_copy_same_content_is_not_merged(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    original = root / "orig.txt"
    original.write_text("same content", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)

    shutil.copy(str(original), str(root / "copy.txt"))
    _, rec = _scan(db, root, volume)

    assert rec["renamed"] == 0
    assert len(db.search_files(limit=100)) == 2


def test_hardlink_is_not_treated_as_rename(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    original = root / "orig.txt"
    original.write_text("hardlink content", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)

    (root / "link.txt").hardlink_to(original)
    _, rec = _scan(db, root, volume)

    # Both paths remain present and ACTIVE; nothing is merged away.
    assert rec["renamed"] == 0
    assert {r["filename"] for r in db.search_files(limit=100)} == {"orig.txt", "link.txt"}


def test_fts_and_sqlite_integrity_after_lifecycle(db: DatabaseManager, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    _scan(db, root, volume)
    file_id = [r for r in db.search_files() if r["filename"] == "a.txt"][0]["id"]
    db.update_content(file_id, "integrity marker")
    (root / "b.txt").unlink()
    _scan(db, root, volume)

    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('integrity-check')")
