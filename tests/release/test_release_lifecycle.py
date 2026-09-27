"""Release scan/lifecycle and crash/restart acceptance (M021, phases 7 & 18)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService, ScanSession
from src.core.volume import VolumeInfo
from src.ingest.pipeline import IngestionPipeline


def _volume(root: Path) -> VolumeInfo:
    return VolumeInfo(stable_key="lifecycle", device="lifecycle",
                      mountpoint=str(root), is_available=True)


def _scan(db, root: Path):
    return ScanService(db).run(ScanRequest(root=root, volume=_volume(root), batch_size=50))


def _active_paths(db) -> list[str]:
    with db.get_connection() as conn:
        return [str(r[0]) for r in conn.execute(
            "SELECT path FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE' ORDER BY path")]


def _all_paths(db) -> list[str]:
    with db.get_connection() as conn:
        return [str(r[0]) for r in conn.execute("SELECT path FROM files ORDER BY path")]


def test_scan_lifecycle_add_modify_rename_delete_readd(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.txt").write_text("alpha lifecycle content one", encoding="utf-8")
    (root / "b.txt").write_text("beta lifecycle content two", encoding="utf-8")
    db = DatabaseManager(tmp_path / "life.db")

    first = _scan(db, root)
    assert first.status == "COMPLETED" and first.files_seen == 2
    assert len(_active_paths(db)) == 2

    # No-change rescan: same paths, no duplicates, no drift.
    second = _scan(db, root)
    assert second.status == "COMPLETED"
    paths = _all_paths(db)
    assert len(paths) == len(set(paths)) == 2

    # Add.
    (root / "c.txt").write_text("gamma lifecycle content three", encoding="utf-8")
    _scan(db, root)
    assert len(_active_paths(db)) == 3

    # Modify (size/mtime change) keeps a single row per path.
    (root / "a.txt").write_text("alpha lifecycle content one extended and changed",
                                encoding="utf-8")
    _scan(db, root)
    assert len(_active_paths(db)) == 3
    assert len(_all_paths(db)) == len(set(_all_paths(db)))

    # Rename.
    (root / "b.txt").rename(root / "b_renamed.txt")
    _scan(db, root)
    active = _active_paths(db)
    assert str(root / "b_renamed.txt") in active
    assert len(active) == len(set(active))
    assert len(active) == 3

    # Delete.
    (root / "c.txt").unlink()
    _scan(db, root)
    with db.get_connection() as conn:
        state = conn.execute("SELECT state FROM files WHERE path=?",
                             (str(root / "c.txt"),)).fetchone()
    assert state is None or state[0] in {"MISSING", "DELETED"}

    # Re-add.
    (root / "c.txt").write_text("gamma lifecycle content three returns", encoding="utf-8")
    _scan(db, root)
    assert str(root / "c.txt") in _active_paths(db)
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_incremental_extraction_does_not_reprocess(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "one.txt").write_text("first incremental document finance", encoding="utf-8")
    (root / "two.txt").write_text("second incremental document health", encoding="utf-8")
    db = DatabaseManager(tmp_path / "inc.db")
    _scan(db, root)
    pipeline = IngestionPipeline(db)
    first = pipeline.run(min_size=1, max_size=10_000_000)
    assert first["counts"].get("EXTRACTED") == 2
    second = pipeline.run(min_size=1, max_size=10_000_000)
    assert second["attempted"] == 0


def test_interrupted_scan_is_recovered_and_rescanned(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    for i in range(4):
        (root / f"f{i}.txt").write_text(f"recovery content {i}", encoding="utf-8")
    db = DatabaseManager(tmp_path / "crash.db")

    # Start a scan and abandon it without recording a terminal status.
    session = ScanSession(db, root, volume=_volume(root))
    session.record([])  # a partial, empty batch
    # Simulate a crash: do not call complete()/fail() explicitly.
    session.__exit__(RuntimeError, RuntimeError("simulated crash"), None)

    with db.get_connection() as conn:
        run = conn.execute("SELECT status FROM scan_runs WHERE id=?", (session.run_id,)).fetchone()
        assert run is not None and run[0] in {"FAILED", "RUNNING", "CANCELLED"}
    recovered = db.recover_stale_runs()
    assert recovered >= 0
    with db.get_connection() as conn:
        status = conn.execute("SELECT status FROM scan_runs WHERE id=?",
                              (session.run_id,)).fetchone()[0]
        assert status in {"FAILED", "CANCELLED"}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    # A subsequent clean scan converges to the correct set.
    result = _scan(db, root)
    assert result.status == "COMPLETED"
    assert len(_active_paths(db)) == 4


def test_source_files_never_modified_by_scan_and_extract(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "keep.txt").write_text("immutable source content finance", encoding="utf-8")
    before = hashlib.sha256((root / "keep.txt").read_bytes()).hexdigest()
    db = DatabaseManager(tmp_path / "safe.db")
    _scan(db, root)
    IngestionPipeline(db).run(min_size=1, max_size=10_000_000)
    after = hashlib.sha256((root / "keep.txt").read_bytes()).hexdigest()
    assert before == after
    assert {p.name for p in root.iterdir()} == {"keep.txt"}
