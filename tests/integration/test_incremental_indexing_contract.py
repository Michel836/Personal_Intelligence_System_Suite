"""Contract tests for incremental indexing safety (M005A.1).

Covers: metadata UPSERT, content preservation, checksum persistence, honest
counts, global scanner limits, cancel reset, large-file metadata visibility,
hashing/extraction thresholds, WAL/SHM safety, repeated opens, concurrency and
Linux timestamp semantics.

Deletion/rename/move reconciliation is intentionally **not** implemented; these
tests only assert that a scan never fabricates deletions.
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.scanner.engine import ScannerEngine
from src.scanner.fast_engine import FastScannerEngine
from src.scanner.models import (
    EXTRACTION_LIMIT,
    HASH_LIMIT,
    FileInfo,
    FileType,
    Priority,
)


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "idx.db")


def _make_tree(root: Path, count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (root / f"f{i:04d}.txt").write_text(f"body {i}", encoding="utf-8")


def _sparse(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.truncate(size)


# --- A/B/C/D/E/F/G: UPSERT contract ---------------------------------------
def test_upsert_inserts_new_file(db, file_info_factory, tmp_path) -> None:
    file_id = db.save_file(file_info_factory(tmp_path / "a.txt", size_bytes=10))
    assert file_id > 0
    rows = db.search_files()
    assert len(rows) == 1
    assert rows[0]["size_bytes"] == 10


def test_upsert_refreshes_modified_metadata(db, file_info_factory, tmp_path) -> None:
    path = tmp_path / "a.txt"
    db.save_file(
        file_info_factory(
            path,
            size_bytes=10,
            extension=".txt",
            file_type=FileType.OTHER,
            priority=Priority.LOW,
            modified_at=datetime(2024, 1, 1),
        )
    )
    db.save_file(
        file_info_factory(
            path,
            size_bytes=99,
            extension=".pdf",
            file_type=FileType.DOCUMENT,
            priority=Priority.HIGH,
            modified_at=datetime(2024, 6, 1),
        )
    )

    rows = db.search_files()
    assert len(rows) == 1
    row = rows[0]
    assert row["size_bytes"] == 99
    assert row["extension"] == ".pdf"
    assert row["file_type"] == "document"
    assert row["priority"] == "high"
    assert row["modified_at"].startswith("2024-06-01")


def test_upsert_preserves_extracted_content(db, file_info_factory, tmp_path) -> None:
    path = tmp_path / "a.txt"
    file_id = db.save_file(file_info_factory(path, size_bytes=10))
    db.update_content(file_id, "extracted payload text")

    # Metadata-only rescan must not wipe extracted content.
    db.save_file(file_info_factory(path, size_bytes=25))

    row = db.search_files()[0]
    assert row["size_bytes"] == 25
    assert row["content_text"] == "extracted payload text"
    assert row["content_extracted"] == 1
    assert len(db.search_files(query="extracted")) == 1


def test_checksum_persists(db, file_info_factory, tmp_path) -> None:
    db.save_file(
        file_info_factory(tmp_path / "a.txt", size_bytes=3, checksum="abc123")
    )
    assert db.search_files()[0]["checksum"] == "abc123"


def test_upsert_produces_no_duplicate_rows(db, file_info_factory, tmp_path) -> None:
    path = tmp_path / "a.txt"
    for size in range(5):
        db.save_file(file_info_factory(path, size_bytes=size))
    assert len(db.search_files()) == 1


def test_batch_upsert_refreshes_and_reports_count(
    db, file_info_factory, tmp_path
) -> None:
    batch = [file_info_factory(tmp_path / f"f{i}.txt", size_bytes=i) for i in range(20)]
    written = db.save_files_batch(batch)
    assert written == 20
    assert len(db.search_files(limit=100)) == 20

    updated = [
        file_info_factory(tmp_path / f"f{i}.txt", size_bytes=i + 100) for i in range(20)
    ]
    assert db.save_files_batch(updated) == 20
    assert len(db.search_files(limit=100)) == 20
    assert {r["size_bytes"] for r in db.search_files(limit=100)} == {
        i + 100 for i in range(20)
    }


# --- H: ScannerEngine global limit ----------------------------------------
def test_scannerengine_limit_is_global(tmp_path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _make_tree(root_a, 100)
    _make_tree(root_b, 100)

    assert len(list(ScannerEngine().scan_paths([root_a], limit=10))) == 10
    assert len(list(ScannerEngine().scan_paths([root_a, root_b], limit=10))) == 10
    assert len(list(ScannerEngine().scan_paths([root_a], limit=None))) == 100
    assert len(list(ScannerEngine().scan_paths([root_a], limit=1000))) == 100


# --- I: FastScanner cancel reset ------------------------------------------
def test_fastscanner_cancel_reset(tmp_path) -> None:
    root = tmp_path / "root"
    _make_tree(root, 5)

    scanner = FastScannerEngine()
    assert len(list(scanner.fast_scan(root))) == 5
    scanner.cancel()
    # A new scan invocation must start from a clean cancellation state.
    assert len(list(scanner.fast_scan(root))) == 5
    assert len(list(scanner.scan_paths([root]))) == 5


# --- J/K/L: large-file visibility, hash and extraction thresholds ----------
def test_large_file_metadata_visible(tmp_path) -> None:
    root = tmp_path / "big"
    _sparse(root / "tiny.bin", 1)
    _sparse(root / "at_hash.bin", HASH_LIMIT)
    _sparse(root / "over_hash.bin", HASH_LIMIT + 1)
    _sparse(root / "two_gb.bin", 2 * 1024 * 1024 * 1024)  # sparse, no real 2GB

    seen = {fi.filename: fi for fi in FastScannerEngine().fast_scan(root)}
    assert set(seen) == {"tiny.bin", "at_hash.bin", "over_hash.bin", "two_gb.bin"}
    assert seen["two_gb.bin"].size_bytes == 2 * 1024 * 1024 * 1024
    assert not seen["two_gb.bin"].checksum  # never hashed


def test_hashing_threshold(tmp_path) -> None:
    root = tmp_path / "hash"
    _sparse(root / "under.bin", HASH_LIMIT - 1)
    _sparse(root / "at.bin", HASH_LIMIT)

    seen = {fi.filename: fi for fi in ScannerEngine().scan_paths([root])}
    assert seen["under.bin"].checksum  # hashed
    assert not seen["at.bin"].checksum  # at/over limit: not hashed


def test_extraction_threshold_contract(db, file_info_factory, tmp_path) -> None:
    db.save_file(
        file_info_factory(
            tmp_path / "small.txt", size_bytes=10, file_type=FileType.DOCUMENT
        )
    )
    db.save_file(
        file_info_factory(
            tmp_path / "big.txt", size_bytes=EXTRACTION_LIMIT, file_type=FileType.DOCUMENT
        )
    )

    names = {r["filename"] for r in db.get_unprocessed_documents()}
    assert "small.txt" in names
    assert "big.txt" not in names


# --- M: WAL/SHM are never unlinked by the harness --------------------------
def test_database_manager_does_not_unlink_wal_shm(tmp_path) -> None:
    path = tmp_path / "wal.db"
    DatabaseManager(path)

    # Hold a connection open so SQLite maintains the WAL/SHM files.
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """INSERT INTO files
           (path, filename, extension, size_bytes, file_type, priority,
            created_at, modified_at)
           VALUES ('/x/f.txt', 'f.txt', '.txt', 1, 'document', 'medium',
                   '2024-01-01', '2024-01-01')"""
    )
    conn.commit()

    wal = Path(str(path) + "-wal")
    assert wal.exists()

    # Age the WAL beyond the old 60s heuristic; reopening must not delete it.
    old = time.time() - 3600
    os.utime(wal, (old, old))
    DatabaseManager(path)
    assert wal.exists()
    conn.close()


# --- N: repeated opens -----------------------------------------------------
def test_repeated_opens_keep_data(file_info_factory, tmp_path) -> None:
    path = tmp_path / "reopen.db"
    seed = DatabaseManager(path)
    file_id = seed.save_file(file_info_factory(tmp_path / "a.txt", size_bytes=1))
    seed.update_content(file_id, "hello world")

    for _ in range(10):
        reopened = DatabaseManager(path)

    rows = reopened.search_files(query="hello")
    assert len(rows) == 1
    assert rows[0]["content_text"] == "hello world"


# --- O: concurrent reader + writer ----------------------------------------
def test_concurrent_reader_and_writer(db, file_info_factory, tmp_path) -> None:
    db.save_file(file_info_factory(tmp_path / "seed.txt", size_bytes=1))
    errors: list[Exception] = []
    import threading

    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                db.search_files(query="seed")
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for i in range(50):
            db.save_file(file_info_factory(tmp_path / f"c{i}.txt", size_bytes=i))
    finally:
        stop.set()
        thread.join(timeout=10)

    assert errors == []
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# --- P: Linux timestamp semantics -----------------------------------------
def test_created_at_is_not_ctime_and_mtime_is_modification(tmp_path) -> None:
    root = tmp_path / "ts"
    root.mkdir()
    target = root / "t.txt"
    target.write_text("x", encoding="utf-8")

    info = {fi.filename: fi for fi in ScannerEngine().scan_paths([root])}["t.txt"]

    assert info.modified_at is not None
    if not hasattr(target.stat(), "st_birthtime"):
        # Linux: no birth time available -> honest None, never ctime.
        assert info.created_at is None

    # chmod / rename must not fabricate a created_at.
    os.chmod(target, 0o600)
    renamed_path = root / "renamed.txt"
    target.rename(renamed_path)
    renamed = {fi.filename: fi for fi in ScannerEngine().scan_paths([root])}
    assert set(renamed) == {"renamed.txt"}
    if not hasattr(renamed_path.stat(), "st_birthtime"):
        assert renamed["renamed.txt"].created_at is None


# --- M005A.1F: unknown scan values must not erase known values -------------
def test_checksum_null_does_not_erase_existing(db, file_info_factory, tmp_path) -> None:
    path = tmp_path / "c.txt"
    db.save_file(file_info_factory(path, size_bytes=1, checksum=None))
    assert db.search_files()[0]["checksum"] is None
    db.save_file(file_info_factory(path, size_bytes=1, checksum="v1"))
    assert db.search_files()[0]["checksum"] == "v1"
    db.save_file(file_info_factory(path, size_bytes=1, checksum="v2"))
    assert db.search_files()[0]["checksum"] == "v2"
    # A scan that did not hash the file sends NULL; the old value survives.
    db.save_file(file_info_factory(path, size_bytes=1, checksum=None))
    assert db.search_files()[0]["checksum"] == "v2"


def test_created_at_null_does_not_erase_existing(db, tmp_path) -> None:
    path = tmp_path / "c.txt"

    def build(created):
        return FileInfo(
            path=path,
            filename=path.name,
            extension=path.suffix,
            size_bytes=1,
            file_type=FileType.DOCUMENT,
            priority=Priority.MEDIUM,
            created_at=created,
            modified_at=datetime(2024, 1, 1),
        )

    db.save_file(build(None))
    assert db.search_files()[0]["created_at"] is None
    db.save_file(build(datetime(2010, 5, 5)))
    assert db.search_files()[0]["created_at"].startswith("2010-05-05")
    db.save_file(build(datetime(2011, 6, 6)))
    assert db.search_files()[0]["created_at"].startswith("2011-06-06")
    # Birth time unavailable this scan: the previously known value survives.
    db.save_file(build(None))
    assert db.search_files()[0]["created_at"].startswith("2011-06-06")


def test_upsert_row_id_is_stable(db, file_info_factory, tmp_path) -> None:
    path = tmp_path / "stable.txt"
    first = db.save_file(file_info_factory(path, size_bytes=1))
    second = db.save_file(file_info_factory(path, size_bytes=2, checksum="x"))
    assert first == second


def test_scannerengine_non_positive_limit_is_unlimited(tmp_path) -> None:
    root = tmp_path / "r"
    _make_tree(root, 30)
    assert len(list(ScannerEngine().scan_paths([root], limit=None))) == 30
    assert len(list(ScannerEngine().scan_paths([root], limit=0))) == 30
    assert len(list(ScannerEngine().scan_paths([root], limit=-1))) == 30


def test_batch_count_is_input_records_not_distinct_rows(
    db, file_info_factory, tmp_path
) -> None:
    written = db.save_files_batch(
        [
            file_info_factory(tmp_path / "dup.txt", size_bytes=1),
            file_info_factory(tmp_path / "dup.txt", size_bytes=2),
        ]
    )
    assert written == 2  # input records processed
    assert len([r for r in db.search_files() if r["filename"] == "dup.txt"]) == 1


# --- Phase 10 adversarial: repeated scans, FTS, 2GB payload not read -------
def test_repeated_scans_and_fts_stay_consistent(db, file_info_factory, tmp_path) -> None:
    path = tmp_path / "repeat.txt"
    for i in range(10):
        db.save_file(file_info_factory(path, size_bytes=i, modified_at=datetime(2024, 1, 1 + i)))
    assert len(db.search_files()) == 1
    assert db.search_files()[0]["size_bytes"] == 9

    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('integrity-check')")
