"""SCAN-UI-01: the Streamlit Scanner page must be a ``ScanService`` client.

The legacy page rebuilt the scan lifecycle by hand
(``list(scanner.scan_paths(...))``, ``ScanSession.complete()``, a post-scan size
filter, a fake thread selector and Pause/Resume).  These tests inspect the real
``src/ui/app.py`` source -- without importing it, so no default database or
Streamlit runtime is touched -- to pin the wiring contract and prevent the unsafe
patterns from silently returning.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[2] / "src" / "ui" / "app.py"


def _source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _function_sources(*names: str) -> str:
    source = _source()
    tree = ast.parse(source)
    wanted = set(names)
    segments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            segments.append(ast.get_source_segment(source, node) or "")
    return "\n".join(segments)


def _scanner_path_source() -> str:
    return _function_sources(
        "scanner_page",
        "_scan_worker",
        "_scanner_drain_updates",
        "_render_scanner_progress",
    )


def test_scanner_routes_through_canonical_scan_service() -> None:
    worker = _function_sources("_scan_worker")
    assert "ScanService" in worker
    assert "ScanRequest" in worker
    assert "service.run(" in worker
    assert "cancel_event=cancel_event" in worker
    assert "progress_callback=progress_callback" in worker


def test_scanner_has_no_manual_lifecycle_or_scan_paths() -> None:
    source = _scanner_path_source()
    assert "scan_paths(" not in source
    assert ".session(" not in source
    assert ".complete()" not in source


def test_scanner_has_no_post_scan_size_filter() -> None:
    source = _scanner_path_source()
    assert "size_bytes >" not in source
    assert "file_limit_mb" not in source
    assert "max_files" not in source


def test_scanner_has_no_pause_or_resume_controls() -> None:
    source = _scanner_path_source()
    assert "pause" not in source.lower()
    assert "resume" not in source.lower()
    assert "render_scan_controls" not in source
    assert "⏸️" not in source
    assert "▶️" not in source


def test_scanner_has_no_fake_threads_selector() -> None:
    source = _function_sources("scanner_page")
    assert "Threads" not in source
    assert "threads" not in source
    # The worker thread used for real cancellation must remain.
    assert "threading.Thread" in source


def test_scanner_stop_uses_a_real_cancel_event() -> None:
    source = _function_sources("scanner_page")
    assert "cancel_event = threading.Event()" in source
    assert "cancel_event.set()" in source


def test_scanner_keeps_statistics_button() -> None:
    assert "Voir les Statistiques" in _function_sources("scanner_page")


def test_legacy_scanner_helpers_are_removed() -> None:
    names = {
        node.name
        for node in ast.walk(ast.parse(_source()))
        if isinstance(node, ast.FunctionDef)
    }
    assert "background_scan_worker" not in names
    assert "_start_advanced_scan" not in names
    assert "_start_advanced_scan_realtime" not in names


def test_no_parallel_scanner_page_architecture() -> None:
    ui = APP_PATH.parent
    assert not (ui / "canonical_app.py").exists()
    assert not (ui / "safe_scanner_page.py").exists()
    assert not (ui / "scanner_runtime.py").exists()
