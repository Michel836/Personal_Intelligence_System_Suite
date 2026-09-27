"""Integration tests for virtual archive members (M009J.4/.14/.19/.20)."""
from __future__ import annotations

import io
import sqlite3
import zipfile
from pathlib import Path

import pytest

from src.archives import limits as limits_mod
from src.archives.indexer import ArchiveIndexer, index_archives_in_db
from src.archives.limits import ArchiveLimits, ArchivePolicy
from src.archives.inspector import ArchiveStatus
from src.core.database import DOC_KIND_MEMBER, DOC_KIND_PHYSICAL, DatabaseManager
from src.scanner.models import FileType


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "archives.db")


def _make_zip(path: Path, entries) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return path


def _parent(db: DatabaseManager, factory, path: Path, file_type=FileType.ARCHIVE) -> int:
    return db.save_file(factory(path, size_bytes=path.stat().st_size, file_type=file_type))


def test_migration_adds_columns_preserves_rows(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.execute(
        "CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL,"
        " filename TEXT NOT NULL, extension TEXT, size_bytes INTEGER, file_type TEXT,"
        " priority TEXT, created_at TEXT, modified_at TEXT, content_text TEXT,"
        " content_extracted BOOLEAN DEFAULT 0, metadata TEXT, indexed_at TEXT,"
        " checksum TEXT, parent_dir TEXT, depth INTEGER)"
    )
    conn.execute("INSERT INTO files (path, filename, modified_at) VALUES ('/old.txt', 'old.txt', '2024-01-01')")
    conn.commit()
    conn.close()

    db = DatabaseManager(legacy)
    with db.get_connection() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(files)")}
        assert {"document_kind", "archive_parent_id", "archive_member_path", "archive_depth",
                "archive_format", "member_state", "extraction_state"} <= cols
        row = c.execute("SELECT filename, document_kind FROM files WHERE path='/old.txt'").fetchone()
    assert row[0] == "old.txt"
    assert row[1] == "PHYSICAL_FILE"


def test_index_zip_creates_virtual_members_and_fts(db, file_info_factory, tmp_path: Path) -> None:
    archive = _make_zip(tmp_path / "backup.zip", [
        ("docs/report.txt", "quarterly contract facture résumé"),
        ("readme.md", "readme notes"),
    ])
    pid = _parent(db, file_info_factory, archive)
    result = ArchiveIndexer(db).index_archive(pid, str(archive))

    assert result.status == ArchiveStatus.OK.value
    assert result.member_count == 2
    members = db.get_archive_members(pid)
    assert len(members) == 2
    assert all(m["document_kind"] == DOC_KIND_MEMBER for m in members)
    assert all(m["path"].startswith(str(archive) + "!/") for m in members)

    # lexical search by member filename and by extracted content
    assert any(r["filename"] == "report.txt" for r in db.search_files("report"))
    assert any(r["path"].endswith("report.txt") for r in db.search_files("facture"))
    assert len(db.search_files(None, document_kind=DOC_KIND_MEMBER)) == 2
    assert len(db.search_files(None, document_kind=DOC_KIND_PHYSICAL)) == 1


def test_index_state_and_unchanged_skip(db, file_info_factory, tmp_path: Path) -> None:
    archive = _make_zip(tmp_path / "a.zip", [("x.txt", "hello")])
    pid = _parent(db, file_info_factory, archive)
    first = ArchiveIndexer(db).index_archive(pid, str(archive))
    assert not first.unchanged
    state = db.get_archive_index_state(pid)
    assert state["archive_status"] == "OK"
    assert state["archive_member_count"] == 1
    assert state["archive_processing_version"]

    second = ArchiveIndexer(db).index_archive(pid, str(archive))
    assert second.unchanged is True

    # processing-version change forces a re-index
    with db.get_connection() as c:
        c.execute("UPDATE files SET archive_processing_version='0' WHERE id=?", (pid,))
        c.commit()
    third = ArchiveIndexer(db).index_archive(pid, str(archive))
    assert third.unchanged is False


def test_reconcile_add_remove_replace(db, file_info_factory, tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    _make_zip(archive, [("keep.txt", "keep"), ("gone.txt", "gone")])
    pid = _parent(db, file_info_factory, archive)
    ArchiveIndexer(db).index_archive(pid, str(archive))
    assert {m["archive_member_path"] for m in db.get_archive_members(pid)} == {"keep.txt", "gone.txt"}

    # modify: change keep content, drop gone, add new
    _make_zip(archive, [("keep.txt", "keep changed"), ("new.txt", "new")])
    ArchiveIndexer(db).index_archive(pid, str(archive))
    active = {m["archive_member_path"]: m for m in db.get_archive_members(pid)}
    assert set(active) == {"keep.txt", "new.txt"}
    allm = {m["archive_member_path"]: m for m in db.get_archive_members(pid, include_missing=True)}
    assert allm["gone.txt"]["member_state"] == "MISSING"
    # changed member resets extracted content
    assert active["keep.txt"]["content_extracted"] == 1
    assert "changed" in (active["keep.txt"]["content_text"] or "")


def test_parent_missing_marks_members_missing(db, file_info_factory, tmp_path: Path) -> None:
    archive = _make_zip(tmp_path / "a.zip", [("x.txt", "hello")])
    pid = _parent(db, file_info_factory, archive)
    ArchiveIndexer(db).index_archive(pid, str(archive))
    assert db.get_archive_members(pid)
    assert db.mark_archive_members_missing(pid) == 1
    assert db.get_archive_members(pid) == []


def test_nested_archive_virtual_paths(db, file_info_factory, tmp_path: Path) -> None:
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("deep/notes.txt", "nested contrats text")
    archive = _make_zip(tmp_path / "outer.zip", [
        ("top.txt", "top facture text"),
        ("inner.zip", inner.getvalue()),
    ])
    pid = _parent(db, file_info_factory, archive)
    result = ArchiveIndexer(db).index_archive(pid, str(archive))
    assert result.nested == 1
    inner_row = next(m for m in db.get_archive_members(pid) if m["archive_member_path"] == "inner.zip")
    deep = db.get_archive_members(inner_row["id"])
    assert deep and deep[0]["path"] == f"{archive}!/inner.zip!/deep/notes.txt"
    assert any(r["path"].endswith("deep/notes.txt") for r in db.search_files("contrats"))


def test_depth_limit_stops_recursion(db, file_info_factory, tmp_path: Path) -> None:
    # Build a genuinely 5-level nested zip chain: leaf at the centre.
    data = None
    for depth in range(5):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            if data is not None:
                zf.writestr("inner.zip", data)
            zf.writestr(f"leaf{depth}.txt", "leaf contrat")
        data = buf.getvalue()
    archive = tmp_path / "deep.zip"
    archive.write_bytes(data)
    pid = _parent(db, file_info_factory, archive)
    indexer = ArchiveIndexer(db, limits=ArchiveLimits(max_depth=2, max_members=100))
    result = indexer.index_archive(pid, str(archive))
    # recursion must always terminate, and never exceed the depth budget
    assert result.status in {ArchiveStatus.OK.value, ArchiveStatus.LIMIT_DEPTH.value}
    assert result.nested <= 3


def test_metadata_only_policy_skips_extraction(db, file_info_factory, tmp_path: Path) -> None:
    archive = _make_zip(tmp_path / "a.zip", [("doc.txt", "searchable content here")])
    pid = _parent(db, file_info_factory, archive)
    db2 = DatabaseManager(tmp_path / "a.db")
    pid2 = _parent(db2, file_info_factory, archive)
    policy = ArchivePolicy(enabled=True, policy=limits_mod.POLICY_METADATA_ONLY)
    result = ArchiveIndexer(db2, policy=policy).index_archive(pid2, str(archive))
    members = db2.get_archive_members(pid2)
    assert result.member_count == 1
    assert all(not m["content_extracted"] for m in members)
    assert db2.search_files("searchable") == []


def test_disabled_policy(db, file_info_factory, tmp_path: Path) -> None:
    archive = _make_zip(tmp_path / "a.zip", [("doc.txt", "x")])
    pid = _parent(db, file_info_factory, archive)
    policy = ArchivePolicy(enabled=False)
    result = ArchiveIndexer(db, policy=policy).index_archive(pid, str(archive))
    assert result.status == ArchiveStatus.DISABLED.value
    assert db.get_archive_members(pid) == []


def test_index_archives_in_db_batch(db, file_info_factory, tmp_path: Path) -> None:
    for i in range(3):
        a = _make_zip(tmp_path / f"a{i}.zip", [(f"f{i}.txt", "batch content")])
        _parent(db, file_info_factory, a)
    results = index_archives_in_db(db)
    assert len(results) == 3
    assert all(r.status == ArchiveStatus.OK.value for r in results)
