"""Per-archive member-extraction time budget (M013-C2).

A single archive with many slow members must not monopolise the pipeline: the
canonical indexer now enforces a total extraction budget, keeps already-extracted
members valid, and resumes only PENDING members on a later run.
"""
from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest

from src.archives.indexer import ArchiveIndexer, index_archives_in_db
from src.archives.inspector import ArchiveStatus
from src.archives.limits import ArchiveLimits, ArchivePolicy
from src.core.database import DatabaseManager
from src.scanner.models import FileType


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "budget.db")


def _make_zip(path: Path, names) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, "content of " + name + " " * 40)
    return path


def _parent(db: DatabaseManager, factory, path: Path) -> int:
    return db.save_file(factory(path, size_bytes=path.stat().st_size, file_type=FileType.ARCHIVE))


def test_extraction_budget_bounds_and_resumes(db, file_info_factory, tmp_path, monkeypatch) -> None:
    archive = _make_zip(tmp_path / "many.zip", [f"doc_{i:02d}.txt" for i in range(10)])
    pid = _parent(db, file_info_factory, archive)

    # Make every member "slow" without a real wait.
    def slow_extract(_self, _inspector, md, _manager, _tmpdir):  # noqa: ANN001
        time.sleep(0.02)
        return "extracted body for " + md["member_path"]

    monkeypatch.setattr(ArchiveIndexer, "_materialize_and_extract", slow_extract)

    tiny = ArchiveLimits(extract_timeout=0.05)
    first = ArchiveIndexer(db, limits=tiny, policy=ArchivePolicy()).index_archive(
        pid, str(archive), extract=True, force=True
    )

    assert first.status == ArchiveStatus.LIMIT_EXTRACT_TIME.value
    assert 1 <= first.extracted < 10
    # Budget exhaustion is transient, never cached -> archive will be retried.
    state = db.get_archive_index_state(pid)
    assert state["archive_status"] == ArchiveStatus.LIMIT_EXTRACT_TIME.value

    members = db.get_archive_members(pid)
    extracted = [m for m in members if m["extraction_state"] == "EXTRACTED"]
    pending = [m for m in members if m["extraction_state"] == "PENDING"]
    assert len(extracted) == first.extracted
    assert extracted and pending
    # Extracted members keep their content; nothing is marked stale.
    assert all(m["content_text"] for m in extracted)

    # A later run with an ample budget must resume and complete only the rest.
    generous = ArchiveLimits(extract_timeout=5.0)
    second = ArchiveIndexer(db, limits=generous, policy=ArchivePolicy()).index_archive(
        pid, str(archive), extract=True
    )
    assert second.status == ArchiveStatus.OK.value
    members2 = db.get_archive_members(pid)
    assert all(m["extraction_state"] == "EXTRACTED" for m in members2)
    assert len(members2) == 10
    # Only the previously-PENDING members were processed on resume.
    assert second.extracted == len(pending)

    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute(
            "SELECT COUNT(*) FROM files WHERE document_kind='ARCHIVE_MEMBER'"
        ).fetchone()[0] == 10


def test_ample_budget_processes_all_members(db, file_info_factory, tmp_path, monkeypatch) -> None:
    archive = _make_zip(tmp_path / "small.zip", ["a.txt", "b.txt", "c.txt"])
    pid = _parent(db, file_info_factory, archive)

    def fast_extract(_self, _inspector, md, _manager, _tmpdir):  # noqa: ANN001
        return "body " + md["member_path"]

    monkeypatch.setattr(ArchiveIndexer, "_materialize_and_extract", fast_extract)
    result = ArchiveIndexer(db, limits=ArchiveLimits(extract_timeout=5.0)).index_archive(
        pid, str(archive), extract=True, force=True
    )
    assert result.status == ArchiveStatus.OK.value
    assert result.extracted == 3
    assert all(m["extraction_state"] == "EXTRACTED" for m in db.get_archive_members(pid))


def test_resume_skips_terminal_members(db, file_info_factory, tmp_path, monkeypatch) -> None:
    archive = _make_zip(tmp_path / "resume.zip", ["a.txt", "b.txt"])
    pid = _parent(db, file_info_factory, archive)

    calls: list[str] = []

    def counting_extract(_self, _inspector, md, _manager, _tmpdir):  # noqa: ANN001
        calls.append(md["member_path"])
        return "body " + md["member_path"]

    monkeypatch.setattr(ArchiveIndexer, "_materialize_and_extract", counting_extract)
    ix = ArchiveIndexer(db, limits=ArchiveLimits(extract_timeout=5.0))
    ix.index_archive(pid, str(archive), extract=True, force=True)
    assert sorted(calls) == ["a.txt", "b.txt"]

    # Second forced pass: nothing is PENDING, so no member is re-read.
    calls.clear()
    ix.index_archive(pid, str(archive), extract=True, force=True)
    assert calls == []


def test_following_archive_continues_after_budget(db, file_info_factory, tmp_path, monkeypatch) -> None:
    a1 = _make_zip(tmp_path / "a_many.zip", [f"a{i}.txt" for i in range(6)])
    a2 = _make_zip(tmp_path / "b_one.zip", ["b.txt"])
    _parent(db, file_info_factory, a1)
    _parent(db, file_info_factory, a2)

    def slow_extract(_self, _inspector, md, _manager, _tmpdir):  # noqa: ANN001
        time.sleep(0.02)
        return "body " + md["member_path"]

    monkeypatch.setattr(ArchiveIndexer, "_materialize_and_extract", slow_extract)
    monkeypatch.setattr(
        ArchiveLimits, "from_env", classmethod(lambda _cls: ArchiveLimits(extract_timeout=0.03))
    )

    results = index_archives_in_db(db, limit=10, force=True)
    # Both archives are still visited even if the first exhausts its budget.
    assert len(results) == 2
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute(
            "SELECT COUNT(*) FROM files WHERE document_kind='ARCHIVE_MEMBER'"
        ).fetchone()[0] == 7
