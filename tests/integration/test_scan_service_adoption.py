"""Adoption tests for the canonical scan orchestrator (M006).

Exercises ``ScanService``/``ScanSession`` end-to-end against temporary roots and
proves failure/cancel/overlap/stale-run protection, Turbo adoption and a full
user journey.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.core.volume import VolumeInfo


def _vol(key: str, mount: Path) -> VolumeInfo:
    return VolumeInfo(
        stable_key=key, device=key, fs_type="testfs",
        mountpoint=str(mount), is_available=True,
    )


@pytest.fixture()
def service(tmp_path: Path) -> ScanService:
    db = DatabaseManager(tmp_path / "svc.db")
    return ScanService(db)


def _tree(root: Path, count: int = 2) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (root / f"f{i}.txt").write_text(f"body {i}", encoding="utf-8")


def _state(db: DatabaseManager) -> dict[str, str]:
    return {
        r["filename"]: r["state"]
        for r in db.search_files(limit=1000, include_missing=True)
    }


def test_service_initial_and_modified(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "v"
    _tree(root)
    first = service.run(ScanRequest(root=root, volume=_vol("V1", tmp_path)))
    assert first.status == "COMPLETED"
    assert first.files_upserted == 2
    assert all(v == "ACTIVE" for v in _state(service.db).values())

    (root / "f0.txt").write_text("body 0 extended", encoding="utf-8")
    second = service.run(ScanRequest(root=root, volume=_vol("V1", tmp_path)))
    assert second.status == "COMPLETED"
    assert service.db.search_files(query="f0")[0]["size_bytes"] == len("body 0 extended")


def test_service_delete_marks_missing(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "v"
    _tree(root)
    volume = _vol("V1", tmp_path)
    service.run(ScanRequest(root=root, volume=volume))
    (root / "f0.txt").unlink()
    result = service.run(ScanRequest(root=root, volume=volume))
    assert result.status == "COMPLETED"
    assert result.missing == 1
    assert _state(service.db)["f0.txt"] == "MISSING"
    assert [r["filename"] for r in service.db.search_files()] == ["f1.txt"]


def test_service_rename_merges(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    source = root / "old.txt"
    source.write_text("rename me", encoding="utf-8")
    volume = _vol("V1", tmp_path)
    service.run(ScanRequest(root=root, volume=volume))
    file_id = service.db.search_files()[0]["id"]
    source.rename(root / "new.txt")
    result = service.run(ScanRequest(root=root, volume=volume))
    assert result.renamed == 1
    row = service.db.search_files()[0]
    assert row["id"] == file_id and row["filename"] == "new.txt"


def test_service_cancel_does_not_reconcile(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "v"
    _tree(root)
    volume = _vol("V1", tmp_path)
    service.run(ScanRequest(root=root, volume=volume))
    (root / "f0.txt").unlink()

    cancel = threading.Event()
    cancel.set()
    result = service.run(ScanRequest(root=root, volume=volume), cancel_event=cancel)
    assert result.status == "CANCELLED"
    assert _state(service.db)["f0.txt"] == "ACTIVE"


def test_service_failure_marks_failed(service: ScanService, tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "v"
    _tree(root)
    volume = _vol("V1", tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(service.db, "record_scan_files", boom)
    result = service.run(ScanRequest(root=root, volume=volume))
    assert result.status == "FAILED"
    assert "db exploded" in (result.error or "")
    with service.db.get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM scan_runs WHERE id = ?", (result.run_id,)
        ).fetchone()[0]
    assert status == "FAILED"


def test_service_overlapping_scan_is_rejected(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "v"
    _tree(root)
    volume = _vol("V1", tmp_path)
    session = service.session(root, volume=volume)  # left RUNNING
    try:
        result = service.run(ScanRequest(root=root / "sub", volume=volume))
        assert result.status == "FAILED"
        assert result.run_id == -1
    finally:
        session.cancel()


def test_recover_stale_runs_never_reconciles(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "v"
    _tree(root)
    volume = _vol("V1", tmp_path)
    service.run(ScanRequest(root=root, volume=volume))
    (root / "f0.txt").unlink()

    # Simulate a process dying mid-scan: a RUNNING run is left behind.
    session = service.session(root, volume=volume)
    recovered = service.db.recover_stale_runs()
    assert recovered >= 1
    with service.db.get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM scan_runs WHERE id = ?", (session.run_id,)
        ).fetchone()[0]
    assert status == "FAILED"
    assert _state(service.db)["f0.txt"] == "ACTIVE"  # recovered run did not reconcile


def test_run_turbo_lifecycle(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "v"
    _tree(root)
    volume = _vol("V1", tmp_path)
    result = service.run_turbo(root, volume=volume)
    assert result.status == "COMPLETED"
    assert result.files_upserted == 2
    assert all(v == "ACTIVE" for v in _state(service.db).values())

    (root / "f0.txt").unlink()
    result = service.run_turbo(root, volume=volume)
    assert result.status == "COMPLETED"
    assert _state(service.db)["f0.txt"] == "MISSING"


def test_user_journey_via_orchestrator(service: ScanService, tmp_path: Path) -> None:
    root = tmp_path / "journey"
    volume = _vol("V1", tmp_path)
    root.mkdir()
    (root / "a.txt").write_text("alpha content", encoding="utf-8")
    (root / "b.txt").write_text("beta content", encoding="utf-8")

    # initial scan + search
    assert service.run(ScanRequest(root=root, volume=volume)).status == "COMPLETED"
    assert len(service.db.search_files(query="a")) >= 1

    # modify + rescan
    (root / "a.txt").write_text("alpha content changed", encoding="utf-8")
    service.run(ScanRequest(root=root, volume=volume))
    assert service.db.search_files(query="a")[0]["size_bytes"] == len("alpha content changed")

    # delete + rescan -> MISSING hidden from normal search
    (root / "b.txt").unlink()
    service.run(ScanRequest(root=root, volume=volume))
    assert _state(service.db)["b.txt"] == "MISSING"
    assert "b.txt" not in [r["filename"] for r in service.db.search_files()]
    assert "b.txt" in [
        r["filename"] for r in service.db.search_files(include_missing=True)
    ]

    # rename + rescan -> stable identity
    file_id = service.db.search_files(query="a")[0]["id"]
    (root / "a.txt").rename(root / "c.txt")
    service.run(ScanRequest(root=root, volume=volume))
    assert service.db.search_files()[0]["id"] == file_id
    assert service.db.search_files()[0]["filename"] == "c.txt"

    # restart: a new DatabaseManager on the same file keeps a coherent index
    reopened = DatabaseManager(service.db.db_path)
    assert _state(reopened)["c.txt"] == "ACTIVE"
    assert _state(reopened)["b.txt"] == "MISSING"
