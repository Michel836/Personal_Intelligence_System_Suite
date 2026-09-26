"""Contract tests for the scanner -> database -> content pipeline.

These pin the *current* documented production contracts:

* ``FastScannerEngine.scan_paths`` yields schema-valid ``FileInfo`` objects;
* scanned metadata is persisted explicitly with ``save_files_batch``;
* content is only searchable after ``DatabaseManager.update_content``;
* ``DatabaseManager.search_files`` performs contiguous ``LIKE`` matching.

Tokenized/multi-word (FTS) search is intentionally out of scope and deferred to
M004B.
"""
from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager
from src.scanner.fast_engine import FastScannerEngine
from src.scanner.models import FileInfo, FileType


def test_scan_paths_yields_schema_valid_fileinfo(tmp_path: Path) -> None:
    (tmp_path / "doc.txt").write_text("hello world", encoding="utf-8")
    (tmp_path / "pic.jpg").touch()

    files = list(FastScannerEngine().scan_paths([tmp_path]))

    assert files
    assert all(isinstance(file_info, FileInfo) for file_info in files)
    assert all(
        file_info.created_at is not None and file_info.modified_at is not None
        for file_info in files
    )


def test_save_files_batch_persists_scanner_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("alpha", encoding="utf-8")
    (source / "b.jpg").touch()

    db = DatabaseManager(tmp_path / "index.db")
    files = list(FastScannerEngine().scan_paths([source]))
    assert files

    saved = db.save_files_batch(files)
    assert saved == len(files)

    rows = db.search_files(limit=100)
    assert {row["filename"] for row in rows} == {file_info.filename for file_info in files}


def test_update_content_required_before_content_is_searchable(
    tmp_path: Path, file_info_factory
) -> None:
    db = DatabaseManager(tmp_path / "index.db")
    file_id = db.save_file(file_info_factory(tmp_path / "contract.txt", size_bytes=10))

    # Metadata exists, but content is not searchable until extraction updates it.
    assert db.search_files(query="uniquemarker") == []
    row = db.search_files(query="contract")[0]
    assert row["content_text"] is None

    db.update_content(file_id, "uniquemarker alpha beta")
    assert len(db.search_files(query="uniquemarker")) == 1


def test_like_search_is_contiguous_substring(tmp_path: Path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "index.db")
    file_id = db.save_file(file_info_factory(tmp_path / "like.txt", size_bytes=10))
    db.update_content(file_id, "content about testing and performance here")

    # Contiguous phrases match.
    assert len(db.search_files(query="testing and performance")) == 1

    # CONTRACT(M004A): non-contiguous multi-word queries are not matched by the
    # current LIKE implementation; tokenized FTS search is deferred to M004B.
    assert db.search_files(query="testing performance") == []


def test_scanner_classifies_common_types(tmp_path: Path) -> None:
    (tmp_path / "report.txt").write_text("text", encoding="utf-8")
    (tmp_path / "photo.jpg").touch()

    files = list(FastScannerEngine().scan_paths([tmp_path]))
    by_name = {file_info.filename: file_info for file_info in files}

    assert by_name["report.txt"].file_type == FileType.DOCUMENT
    assert by_name["photo.jpg"].file_type == FileType.IMAGE
