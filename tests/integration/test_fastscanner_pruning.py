"""Regression: FastScannerEngine must prune system dirs by path component.

The old substring check silently skipped any directory whose full path merely
contained a skip word (e.g. ``~/recovery_notes``), dropping real files from the
index. This is a data-completeness defect, not a cosmetic one.

The exclusion policy must also prune VCS/virtualenv/build/cache components
*exactly* without pruning legitimate names that merely contain those words.
"""
from __future__ import annotations

from pathlib import Path

from src.scanner.fast_engine import FastScannerEngine

EXCLUDED_COMPONENTS = [
    ".git", ".hg", ".svn",
    ".venv", "venv", "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nox",
    "dist", "build",
    "coverage", ".cache",
]

KEPT_COMPONENTS = [
    "project-recovery-tool",
    "gitlab",
    "vein",
    "environment",
    "distribution",
    "building",
    "node_modules_backup",
]


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


def test_excludes_vcs_venv_build_cache_components(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "keep.txt").write_text("keep", encoding="utf-8")
    for component in EXCLUDED_COMPONENTS:
        directory = root / component
        directory.mkdir()
        (directory / "hidden.txt").write_text("x", encoding="utf-8")

    found = {f.filename for f in FastScannerEngine().fast_scan(root)}

    assert found == {"keep.txt"}


def test_legitimate_names_containing_skip_words_are_kept(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    for component in KEPT_COMPONENTS:
        directory = root / component
        directory.mkdir()
        (directory / "keep.txt").write_text("k", encoding="utf-8")

    found = [f.filename for f in FastScannerEngine().fast_scan(root)]

    # One keep.txt per directory, none pruned.
    assert len(found) == len(KEPT_COMPONENTS)
