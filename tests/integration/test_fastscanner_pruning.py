"""Regression: FastScannerEngine must prune system dirs by path component.

The old substring check silently skipped any directory whose full path merely
contained a skip word (e.g. ``~/recovery_notes``), dropping real files from the
index. This is a data-completeness defect, not a cosmetic one.
"""
from __future__ import annotations

from pathlib import Path

from src.scanner.fast_engine import FastScannerEngine


def test_prunes_exact_component_only(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "normal").mkdir(parents=True)
    (root / "normal" / "a.txt").write_text("a", encoding="utf-8")
    # Legitimate dirs whose names *contain* skip words as substrings.
    (root / "recovery_notes").mkdir()
    (root / "recovery_notes" / "b.txt").write_text("b", encoding="utf-8")
    (root / "windows-notes").mkdir()
    (root / "windows-notes" / "c.txt").write_text("c", encoding="utf-8")
    # A real system directory component must still be pruned.
    (root / "windows").mkdir()
    (root / "windows" / "d.txt").write_text("d", encoding="utf-8")

    found = {f.filename for f in FastScannerEngine().fast_scan(root)}

    assert {"a.txt", "b.txt", "c.txt"} <= found
    assert "d.txt" not in found
