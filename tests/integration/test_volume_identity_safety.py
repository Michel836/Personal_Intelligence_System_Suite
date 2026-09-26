"""Hostile-review tests: reconciliation must verify volume identity.

A completed scan may only reconcile when the volume resolved from the run root
still matches the volume that was scanned. If the mountpoint now belongs to a
different device (or the disk is unmounted), reconciliation must refuse and mark
the run FAILED.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import src.core.database as database
from src.core.database import DatabaseManager
from src.core.volume import VolumeInfo, resolve_volume
from src.scanner.fast_engine import FastScannerEngine


def _verified(key: str, mount: Path) -> VolumeInfo:
    return VolumeInfo(
        stable_key=key, device=key, fs_type="testfs",
        mountpoint=str(mount), is_available=True, identity_verified=True,
    )


def _scan(db: DatabaseManager, root: Path, volume: VolumeInfo):
    info = db.begin_scan(root, volume=volume)
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([root])))
    return info, db.complete_scan(info["run_id"])


def _state(db: DatabaseManager) -> str:
    return db.search_files(limit=100, include_missing=True)[0]["state"]


def test_resolve_volume_marks_identity_verified(tmp_path: Path) -> None:
    resolved = resolve_volume(tmp_path)
    assert resolved.identity_verified is True


def test_identity_change_refuses_reconcile(tmp_path: Path, monkeypatch) -> None:
    db = DatabaseManager(tmp_path / "id.db")
    root = tmp_path / "v"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("a", encoding="utf-8")

    volume = _verified("V1", tmp_path)
    monkeypatch.setattr(
        database,
        "resolve_volume",
        lambda path: VolumeInfo(
            stable_key="V1", mountpoint=str(path), is_available=True,
            identity_verified=True,
        ),
    )
    _scan(db, root, volume)
    target.unlink()

    # Simulate the mountpoint now resolving to a different device.
    monkeypatch.setattr(
        database,
        "resolve_volume",
        lambda path: VolumeInfo(
            stable_key="OTHER", mountpoint=str(path), is_available=True,
            identity_verified=True,
        ),
    )
    info = db.begin_scan(root, volume=volume)
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([root])))
    with pytest.raises(ValueError):
        db.complete_scan(info["run_id"])

    assert _state(db) == "ACTIVE"  # no false deletion
    with db.get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM scan_runs WHERE id = ?", (info["run_id"],)
        ).fetchone()[0]
    assert status == "FAILED"


def test_verified_identity_allows_reconcile(tmp_path: Path, monkeypatch) -> None:
    db = DatabaseManager(tmp_path / "ok.db")
    root = tmp_path / "v"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("a", encoding="utf-8")
    volume = _verified("V1", tmp_path)
    monkeypatch.setattr(
        database,
        "resolve_volume",
        lambda path: VolumeInfo(
            stable_key="V1", mountpoint=str(path), is_available=True,
            identity_verified=True,
        ),
    )
    _scan(db, root, volume)
    target.unlink()

    info = db.begin_scan(root, volume=volume)
    db.record_scan_files(info["run_id"], list(FastScannerEngine().scan_paths([root])))
    result = db.complete_scan(info["run_id"])
    assert result["missing"] == 1
    assert _state(db) == "MISSING"
