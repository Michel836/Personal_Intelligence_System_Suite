"""Bounded estimator contract for the Scanner progress bar (SCAN-UI-01B).

The estimator must be cheap, read-only and fail-safe: it never follows
symlinks, respects the scanner's filesystem boundary, reuses the scanner's skip
rules, is bounded in time/dirs/files, and never raises when an estimate is
impossible.
"""
from __future__ import annotations

import threading
from pathlib import Path

from src.core import scan_estimator
from src.core.scan_estimator import estimate_files


def _tree(root: Path) -> None:
    (root / "a.txt").write_text("a", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b", encoding="utf-8")
    (sub / "c.bin").write_text("c", encoding="utf-8")


def test_estimate_counts_regular_files(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = estimate_files(tmp_path)
    assert result.available is True
    assert result.estimated_files == 3
    assert result.complete is True


def test_estimate_does_not_follow_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.txt").write_text("x", encoding="utf-8")
    (tmp_path / "link_dir").symlink_to(target, target_is_directory=True)
    (tmp_path / "link_file.txt").symlink_to(target / "inside.txt")

    result = estimate_files(tmp_path)

    # Only the real target/inside.txt counts; symlink dir/file are ignored.
    assert result.estimated_files == 1


def test_estimate_reuses_scanner_directory_skips(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "dep.js").write_text("x", encoding="utf-8")

    result = estimate_files(tmp_path)

    assert result.estimated_files == 1


def test_estimate_is_bounded_by_max_files(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")

    result = estimate_files(tmp_path, max_files=3)

    assert result.estimated_files == 3
    assert result.complete is False
    assert result.reason == "max_files"


def test_estimate_is_bounded_by_max_dirs(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"d{i}").mkdir()

    result = estimate_files(tmp_path, max_dirs=2)

    assert result.complete is False
    assert result.reason == "max_dirs"


def test_estimate_is_bounded_by_time(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    result = estimate_files(tmp_path, max_seconds=0)

    assert result.complete is False
    assert result.reason == "time_budget"


def test_estimate_respects_filesystem_boundary(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "local.txt").write_text("x", encoding="utf-8")
    (root / "alias.txt").symlink_to(root / "local.txt")
    foreign = root / "foreign"
    foreign.mkdir()
    (foreign / "hidden.txt").write_text("x", encoding="utf-8")

    real_device = scan_estimator._filesystem_device

    def fake_device(path):
        candidate = Path(path)
        try:
            candidate.relative_to(foreign)
        except ValueError:
            return real_device(root)
        return 999_999

    monkeypatch.setattr(scan_estimator, "_filesystem_device", fake_device)
    result = estimate_files(root)

    assert result.available is True
    assert result.estimated_files == 1  # only local.txt


def test_estimate_rejects_pseudo_filesystem(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(scan_estimator, "is_pseudo_filesystem", lambda _path: True)

    result = estimate_files(tmp_path)

    assert result.available is False
    assert result.estimated_files == 0
    assert result.reason == "pseudo_filesystem"


def test_estimate_cancel_event_stops_cleanly(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    cancel = threading.Event()
    cancel.set()

    result = estimate_files(tmp_path, cancel_event=cancel)

    assert result.available is True
    assert result.complete is False
    assert result.reason == "cancelled"


def test_estimate_never_raises_on_missing_root(tmp_path: Path) -> None:
    result = estimate_files(tmp_path / "does-not-exist")
    assert result.available is False
    assert result.estimated_files == 0


def test_estimate_never_raises_on_unexpected_error(tmp_path: Path, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic estimator failure")

    monkeypatch.setattr(scan_estimator, "is_pseudo_filesystem", boom)
    result = estimate_files(tmp_path)
    assert result.available is False
    assert "synthetic estimator failure" in result.reason


def test_estimator_never_touches_the_database() -> None:
    source = Path(scan_estimator.__file__).read_text(encoding="utf-8")
    assert "DatabaseManager" not in source
    assert "record_scan_files" not in source
    assert "scan_runs" not in source
