"""Canonical scan lifecycle contract consumed by the Streamlit Scanner.

SCAN-UI-01 requires the UI to delegate to ``ScanService.run`` instead of
rebuilding ``begin_scan``/``record_scan_files``/``complete_scan`` by hand.  These
tests pin the exact COMPLETED / CANCELLED / FAILED semantics the page relies on:

* a complete traversal reconciles and ends COMPLETED;
* a deliberately bounded traversal ends CANCELLED and never reconciles;
* an explicit ``cancel_event`` ends CANCELLED and never reconciles;
* a traversal error ends FAILED and never reconciles.
"""
from __future__ import annotations

import threading
from pathlib import Path

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.core.volume import VolumeInfo
from src.scanner.fast_engine import FastScannerEngine


def _vol(key: str, mount: Path) -> VolumeInfo:
    return VolumeInfo(
        stable_key=key,
        device=key,
        fs_type="testfs",
        mountpoint=str(mount),
        is_available=True,
    )


def _tree(root: Path, count: int = 3) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (root / f"f{i}.txt").write_text(f"body {i}", encoding="utf-8")


def _states(db: DatabaseManager) -> dict[str, str]:
    return {
        row["filename"]: row["state"]
        for row in db.search_files(limit=1000, include_missing=True)
    }


def test_complete_scan_is_completed_and_reconciles(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "svc.db")
    service = ScanService(db)
    root = tmp_path / "v"
    _tree(root, count=3)

    result = service.run(ScanRequest(root=root, volume=_vol("V1", tmp_path)))

    assert result.status == "COMPLETED"
    assert result.files_seen == 3
    assert result.files_upserted == 3
    assert all(state == "ACTIVE" for state in _states(db).values())


def test_limited_scan_is_cancelled_without_reconciliation(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "svc.db")
    service = ScanService(db)
    root = tmp_path / "v"
    _tree(root, count=4)
    volume = _vol("V1", tmp_path)
    assert service.run(ScanRequest(root=root, volume=volume)).status == "COMPLETED"

    (root / "f0.txt").unlink()
    result = service.run(ScanRequest(root=root, limit=1, volume=volume))

    assert result.status == "CANCELLED"
    assert result.error and "reconciliation" in result.error
    # A bounded traversal never proves deletion of a path it did not visit.
    assert _states(db)["f0.txt"] == "ACTIVE"


def test_cancel_event_is_cancelled_without_reconciliation(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "svc.db")
    service = ScanService(db)
    root = tmp_path / "v"
    _tree(root, count=4)
    volume = _vol("V1", tmp_path)
    service.run(ScanRequest(root=root, volume=volume))

    (root / "f0.txt").unlink()
    cancel = threading.Event()
    cancel.set()
    result = service.run(ScanRequest(root=root, volume=volume), cancel_event=cancel)

    assert result.status == "CANCELLED"
    assert _states(db)["f0.txt"] == "ACTIVE"


def test_traversal_error_is_failed_without_reconciliation(
    tmp_path: Path, monkeypatch
) -> None:
    db = DatabaseManager(tmp_path / "svc.db")
    service = ScanService(db)
    root = tmp_path / "v"
    _tree(root, count=4)
    volume = _vol("V1", tmp_path)
    service.run(ScanRequest(root=root, volume=volume))

    (root / "f0.txt").unlink()

    def broken_scan_paths(*_args, **_kwargs):
        raise OSError("synthetic traversal failure")
        yield  # pragma: no cover - keeps this a generator function

    monkeypatch.setattr(FastScannerEngine, "scan_paths", broken_scan_paths)
    result = service.run(ScanRequest(root=root, volume=volume))

    assert result.status == "FAILED"
    assert "synthetic traversal failure" in (result.error or "")
    assert _states(db)["f0.txt"] == "ACTIVE"
