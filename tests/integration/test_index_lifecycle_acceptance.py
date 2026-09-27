"""End-to-end acceptance for the incremental index lifecycle (M005A.5).

Simulates a realistic multi-root, multi-volume corpus across several scan runs
and asserts the lifecycle invariants: reversible MISSING states, failed/
cancelled/disconnected protection, rename/move identity, large-file metadata,
idempotence and integrity.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.core.volume import VolumeInfo
from src.scanner.fast_engine import FastScannerEngine

GB = 1024 * 1024 * 1024


def _vol(key: str, mount: Path, *, available: bool = True) -> VolumeInfo:
    return VolumeInfo(
        stable_key=key, device=key, fs_type="testfs",
        mountpoint=str(mount), is_available=available,
    )


def _run(db: DatabaseManager, root: Path, volume: VolumeInfo):
    info = db.begin_scan(root, volume=volume)
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([root])))
    return info, db.complete_scan(info["run_id"])


def _rows(db: DatabaseManager) -> dict[str, dict]:
    return {row["filename"]: row for row in db.search_files(limit=1000, include_missing=True)}


@pytest.fixture()
def corpus(tmp_path: Path):
    db = DatabaseManager(tmp_path / "e2e.db")
    a = tmp_path / "volume-A"
    b = tmp_path / "volume-B"
    for sub in ("Documents", "Photos", "Archive"):
        (a / sub).mkdir(parents=True)
    (b / "Backup").mkdir(parents=True)

    files = {}
    files["docs"] = [a / "Documents" / f"doc{i}.txt" for i in range(3)]
    files["photos"] = [a / "Photos" / f"pic{i}.jpg" for i in range(2)]
    files["archive"] = [a / "Archive" / f"old{i}.dat" for i in range(2)]
    files["backup"] = [b / "Backup" / f"bk{i}.txt" for i in range(2)]
    for group in files.values():
        for path in group:
            path.write_text(path.name, encoding="utf-8")
    return db, a, b, files


def test_end_to_end_lifecycle(corpus) -> None:
    db, a, b, files = corpus
    vol_a = _vol("VOL-A", a)
    vol_b = _vol("VOL-B", b)

    # RUN 1 — initial scan: everything ACTIVE
    _run(db, a, vol_a)
    _run(db, b, vol_b)
    assert len(db.search_files(limit=1000)) == 9
    assert all(r["state"] == "ACTIVE" for r in _rows(db).values())

    # RUN 2 — modify files: metadata refreshed
    time.sleep(0.01)
    for path in files["docs"]:
        path.write_text(path.name * 5, encoding="utf-8")
    _, rec = _run(db, a, vol_a)
    assert rec["missing"] == 0
    for path in files["docs"]:
        assert _rows(db)[path.name]["size_bytes"] == len(path.read_text(encoding="utf-8"))

    # RUN 3 — delete + rename + move + large sparse file
    deleted = files["docs"][0]
    renamed = files["photos"][0]
    moved = files["archive"][0]
    renamed_id = _rows(db)[renamed.name]["id"]
    moved_id = _rows(db)[moved.name]["id"]
    deleted.unlink()
    renamed.rename(a / "Photos" / "renamed.jpg")
    moved.rename(a / "Documents" / "moved.dat")
    large = a / "Archive" / "huge.bin"
    with open(large, "wb") as handle:
        handle.truncate(2 * GB)

    _, rec = _run(db, a, vol_a)
    rows = _rows(db)
    assert rec["missing"] == 1
    assert rows[deleted.name]["state"] == "MISSING"
    assert "renamed.jpg" in rows and rows["renamed.jpg"]["state"] == "ACTIVE"
    assert rows["renamed.jpg"]["id"] == renamed_id
    assert rows["moved.dat"]["id"] == moved_id
    assert rows["huge.bin"]["state"] == "ACTIVE"
    assert rows["huge.bin"]["size_bytes"] == 2 * GB
    assert not rows["huge.bin"]["checksum"]
    # no stale ACTIVE duplicates
    active = [r for r in db.search_files(limit=1000)]
    assert len(active) == len({r["path"] for r in active})

    # RUN 4 — cancelled scan must not reconcile
    cancelled_target = files["docs"][1]
    cancelled_target.unlink()
    info = db.begin_scan(a, volume=vol_a)
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([a])))
    db.cancel_scan(info["run_id"])
    assert _rows(db)[cancelled_target.name]["state"] == "ACTIVE"

    # RUN 5 — volume-B disconnected: never mass-MISSING
    info = db.begin_scan(b, volume=_vol("VOL-B", b, available=False))
    db.record_scan_files(info["run_id"], [])
    with pytest.raises(ValueError):
        db.complete_scan(info["run_id"])
    assert all(_rows(db)[p.name]["state"] == "ACTIVE" for p in files["backup"])

    # RUN 6 — reconnect volume-B: ACTIVE maintained
    _, rec = _run(db, b, vol_b)
    assert rec["missing"] == 0
    assert all(_rows(db)[p.name]["state"] == "ACTIVE" for p in files["backup"])

    # RUN 7 — settle the pending (cancelled) deletion, then prove repeated
    # no-change scans are idempotent.
    _run(db, a, vol_a)
    before = {name: (r["state"], r["size_bytes"]) for name, r in _rows(db).items()}
    assert before[cancelled_target.name][0] == "MISSING"
    _run(db, a, vol_a)
    _run(db, b, vol_b)
    after = {name: (r["state"], r["size_bytes"]) for name, r in _rows(db).items()}
    assert before == after

    # Integrity
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('integrity-check')")


def test_incomplete_run_cannot_reconcile(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "crash.db")
    root = tmp_path / "v"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("a", encoding="utf-8")
    volume = _vol("VOL-C", root)
    _run(db, root, volume)
    target.unlink()

    # Start a run and "crash" (never complete/cancel).
    info = db.begin_scan(root, volume=volume)
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([root])))
    assert _rows(db)["a.txt"]["state"] == "ACTIVE"

    # Explicit failure also never reconciles.
    db.fail_scan(info["run_id"], "simulated crash")
    assert _rows(db)["a.txt"]["state"] == "ACTIVE"

    # A fresh run may now start (no RUNNING overlap) and reconcile correctly.
    _, rec = _run(db, root, volume)
    assert rec["missing"] == 1
    assert _rows(db)["a.txt"]["state"] == "MISSING"


def test_large_file_metadata_only(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "large.db")
    root = tmp_path / "v"
    root.mkdir()
    large = root / "big.bin"
    with open(large, "wb") as handle:
        handle.truncate(2 * GB)
    _, rec = _run(db, root, _vol("VOL-L", root))
    row = _rows(db)["big.bin"]
    assert rec["missing"] == 0
    assert row["state"] == "ACTIVE"
    assert row["size_bytes"] == 2 * GB
    assert not row["checksum"]
