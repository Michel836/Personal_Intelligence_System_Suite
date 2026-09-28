import os
import sqlite3
from pathlib import Path

import pytest

from src.core.scan_service import ScanRequest, ScanService
from src.scanner.fast_engine import FastScannerEngine
from src.search.advanced_search import AdvancedSearch


def test_fast_scan_propagates_unexpected_walk_failure(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("a")

    def broken_walk(root, **kwargs):
        yield str(tmp_path), [], ["a.txt"]
        raise OSError("synthetic traversal failure")

    monkeypatch.setattr("src.scanner.fast_engine.os.walk", broken_walk)

    scanner = FastScannerEngine()
    with pytest.raises(OSError, match="synthetic traversal failure"):
        list(scanner.fast_scan(tmp_path))


def test_fast_scan_skips_fifo(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unsupported on this platform")

    fifo = tmp_path / "looks-like-document.txt"
    os.mkfifo(fifo)

    files = list(FastScannerEngine().fast_scan(tmp_path))
    assert str(fifo) not in {str(item.path) for item in files}


def test_include_system_controls_hidden_files(tmp_path):
    hidden = tmp_path / ".private-note.txt"
    hidden.write_text("secret")

    scanner = FastScannerEngine()
    assert list(scanner.fast_scan(tmp_path, include_system=False)) == []

    visible = list(scanner.fast_scan(tmp_path, include_system=True))
    assert [item.filename for item in visible] == [hidden.name]


def test_scan_service_transports_producer_exception():
    class BrokenScanner:
        def scan_paths(self, *args, **kwargs):
            raise RuntimeError("producer exploded")
            yield  # pragma: no cover

    service = ScanService(db=None)  # _iter_files does not touch DB
    request = ScanRequest(root=Path("/synthetic"))

    with pytest.raises(RuntimeError, match="producer exploded"):
        list(service._iter_files(BrokenScanner(), request, None, overlap=True))


def test_advanced_search_hides_missing_rows_by_default(tmp_path):
    db_path = tmp_path / "search.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE files (
            id INTEGER PRIMARY KEY,
            path TEXT,
            filename TEXT,
            file_type TEXT,
            size_bytes INTEGER,
            modified_at TEXT,
            content_text TEXT,
            indexed_at TEXT,
            state TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO files VALUES (1, '/active.txt', 'active.txt', 'document', 1, '2026-01-01', '', '2026-01-01', 'ACTIVE')"
    )
    conn.execute(
        "INSERT INTO files VALUES (2, '/gone.txt', 'gone.txt', 'document', 1, '2026-01-01', '', '2026-01-01', 'MISSING')"
    )
    conn.commit()
    conn.close()

    search = AdvancedSearch(db_path=db_path)
    result = search.search(limit=10)
    assert result["success"] is True
    assert result["total_count"] == 1
    assert [row["filename"] for row in result["results"]] == ["active.txt"]

    with_missing = search.search(limit=10, include_missing=True)
    assert with_missing["total_count"] == 2
