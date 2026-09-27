"""Regression tests for the M013 scale-preflight discovery tool.

The tool duplicates the production scanner exclusion model so it can run before
the application imports. These tests fail fast if that duplication ever drifts
from :class:`src.scanner.fast_engine.FastScannerEngine`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from src.scanner.fast_engine import FastScannerEngine

_TOOL = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "bench"
    / "m013_preflight.py"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("m013_preflight", _TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load_tool()


def test_skip_dirs_match_production() -> None:
    engine = FastScannerEngine()
    assert engine._skip_dirs == preflight.SKIP_DIRS


def test_skip_extensions_match_production() -> None:
    engine = FastScannerEngine()
    assert engine._skip_extensions == preflight.SKIP_EXT


def test_skipped_dir_is_component_based() -> None:
    assert preflight.skipped_dir(("home", "user", "recovery"))
    assert preflight.skipped_dir(("home", "user", "node_modules", "pkg"))
    # A substring must never prune a legitimate path.
    assert not preflight.skipped_dir(("home", "user", "recovery_notes"))
    assert not preflight.skipped_dir(("home", "user", "windows-notes"))


def test_skipped_file_semantics() -> None:
    assert preflight.skipped_file(".env")
    assert preflight.skipped_file("archive.log")
    assert preflight.skipped_file("library.dll")
    assert not preflight.skipped_file("report.pdf")
    assert not preflight.skipped_file("notes.md")


def test_archive_format_prefers_longest_suffix() -> None:
    assert preflight.archive_format("data.tar.gz") == "TAR_GZ"
    assert preflight.archive_format("data.gz") == "GZ"
    assert preflight.archive_format("data.TAR.GZ") == "TAR_GZ"
    assert preflight.archive_format("data.zip") == "ZIP"
    assert preflight.archive_format("data.txt") is None


def test_category_classification() -> None:
    assert preflight.category_for("a.pdf") == "pdf"
    assert preflight.category_for("a.docx") == "office"
    assert preflight.category_for("a.zip") == "archive"
    assert preflight.category_for("a.png") == "image"
    assert preflight.category_for("a.py") == "code"
    assert preflight.category_for("README") == "extensionless"


def test_scan_root_counts_and_exclusions(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("hello")
    (tmp_path / "docs" / "b.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "trace.log").write_text("x")
    (tmp_path / "bundle.zip").write_bytes(b"PK\x03\x04")
    # Excluded subtree must not contribute to eligible counts.
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x")

    result = preflight.scan_root(str(tmp_path), max_files=10_000)

    assert result["eligible_physical_files"] == 3  # a.txt, b.pdf, bundle.zip
    assert result["hidden_files"] == 1
    assert result["ignored_ext_files"] == 1
    assert result["excluded_dir_prunes"] == 1
    assert result["truncated"] is False
    assert result["ext_counts"][".txt"] == 1
    assert result["archives"] == 1
    assert result["canonical_archives"] == 1


def test_scan_root_truncates_at_max_files(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")
    result = preflight.scan_root(str(tmp_path), max_files=4)
    assert result["truncated"] is True
    assert result["eligible_physical_files"] == 4
