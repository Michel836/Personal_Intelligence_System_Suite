"""Security and failure-matrix tests for archive support (M009J.11/.12/.24/.25)."""
from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest

import src.archives.indexer as indexer_mod
import src.archives.inspector as insp
from src.archives.indexer import ArchiveIndexer, index_archives_in_db
from src.archives.inspector import ArchiveStatus
from src.archives.limits import ArchiveLimits
from src.core.database import DatabaseManager
from src.scanner.models import FileType

SEVENZIP = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "archives-sec.db")


def _parent(db, factory, path: Path, file_type=FileType.ARCHIVE) -> int:
    return db.save_file(factory(path, size_bytes=path.stat().st_size, file_type=file_type))


def _slip_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name in ("../escape.txt", "../../escape2.txt", "/abs.txt",
                     "C:\\win.txt", "\\\\srv\\share.txt", "folder/../../../out.txt"):
            zf.writestr(name, "pwned")
        zf.writestr("safe/ok.txt", "fine")
    return path


def _slip_tar(path: Path) -> Path:
    with tarfile.open(path, "w") as tf:
        for name in ("../escape.txt", "/abs.txt", "../../escape2.txt"):
            ti = tarfile.TarInfo(name)
            ti.size = 3
            tf.addfile(ti, io.BytesIO(b"bad"))
        good = tarfile.TarInfo("safe/ok.txt")
        good.size = 4
        tf.addfile(good, io.BytesIO(b"fine"))
    return path


def test_zip_slip_cannot_escape(db, file_info_factory, tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    archive = _slip_zip(sandbox / "slip.zip")
    pid = _parent(db, file_info_factory, archive)
    ArchiveIndexer(db).index_archive(pid, str(archive))
    members = {m["archive_member_path"] for m in db.get_archive_members(pid)}
    assert members == {"safe/ok.txt"}
    # nothing was written outside the archive
    written = {p.name for p in sandbox.iterdir()}
    assert written == {"slip.zip"}
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path.parent / "escape2.txt").exists()


def test_tar_slip_cannot_escape(db, file_info_factory, tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    archive = _slip_tar(sandbox / "slip.tar")
    pid = _parent(db, file_info_factory, archive)
    ArchiveIndexer(db).index_archive(pid, str(archive))
    members = {m["archive_member_path"] for m in db.get_archive_members(pid)}
    assert members == {"safe/ok.txt"}
    assert {p.name for p in sandbox.iterdir()} == {"slip.tar"}


def test_temp_materialization_is_cleaned(db, file_info_factory, tmp_path: Path, monkeypatch) -> None:
    sandbox = tmp_path / "tmproot"
    sandbox.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(sandbox))
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("notes.txt", "temp cleanliness content")
        zf.writestr("more.txt", "another member")
    pid = _parent(db, file_info_factory, archive)
    ArchiveIndexer(db).index_archive(pid, str(archive))
    # all bounded temp materialization is removed after indexing
    leftovers = list(sandbox.iterdir())
    assert leftovers == [], f"temp files leaked: {leftovers}"


def test_decompression_bomb_is_bounded(db, file_info_factory, tmp_path: Path) -> None:
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zero.bin", "\x00" * 20_000_000)  # compresses to almost nothing
    pid = _parent(db, file_info_factory, archive)
    limits = ArchiveLimits(max_member_bytes=1024, max_total_uncompressed=1024 * 1024, max_ratio=50)
    result = ArchiveIndexer(db, limits=limits).index_archive(pid, str(archive))
    assert result.status == ArchiveStatus.LIMIT_MEMBER_SIZE.value
    assert db.get_archive_members(pid) == []
    # the archive row itself is still searchable as a physical file
    assert any(r["filename"] == "bomb.zip" for r in db.search_files("bomb"))


def test_member_count_bomb_is_bounded(db, file_info_factory, tmp_path: Path) -> None:
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for i in range(500):
            zf.writestr(f"f{i}.txt", "x")
    pid = _parent(db, file_info_factory, archive)
    result = ArchiveIndexer(db, limits=ArchiveLimits(max_members=10)).index_archive(pid, str(archive))
    assert result.status == ArchiveStatus.LIMIT_MEMBER_COUNT.value


def test_failure_matrix_does_not_abort_batch(db, file_info_factory, tmp_path: Path, monkeypatch) -> None:
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("ok.txt", "good content here")

    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"PK\x03\x04garbagegarbage")

    truncated = tmp_path / "trunc.tar"
    with tarfile.open(tmp_path / "full.tar", "w") as tf:
        ti = tarfile.TarInfo("a.txt")
        ti.size = 3
        tf.addfile(ti, io.BytesIO(b"abc"))
    truncated.write_bytes((tmp_path / "full.tar").read_bytes()[:256])

    fake_rar = tmp_path / "fake.rar"
    fake_rar.write_bytes(b"not really a rar file")
    monkeypatch.setattr(insp, "_rar_backend_available", lambda: False)

    for p in (good, corrupt, truncated, fake_rar):
        _parent(db, file_info_factory, p)

    results = index_archives_in_db(db)
    statuses = {Path(r.path).name: r.status for r in results}
    assert statuses["good.zip"] == ArchiveStatus.OK.value
    assert statuses["corrupt.zip"] == ArchiveStatus.CORRUPT_ARCHIVE.value
    assert statuses["trunc.tar"] in {ArchiveStatus.CORRUPT_ARCHIVE.value, ArchiveStatus.OK.value}
    assert statuses["fake.rar"] in {ArchiveStatus.BACKEND_UNAVAILABLE.value, ArchiveStatus.CORRUPT_ARCHIVE.value}
    # the good archive still produced searchable members
    assert any(r["filename"] == "ok.txt" for r in db.search_files(None))


@pytest.mark.skipif(SEVENZIP is None, reason="no 7z backend")
def test_password_archive_does_not_abort(db, file_info_factory, tmp_path: Path) -> None:
    f = tmp_path / "note.txt"
    f.write_text("secret")
    pwd = tmp_path / "locked.7z"
    subprocess.run([SEVENZIP, "a", "-t7z", "-psecret", str(pwd), str(f)], capture_output=True, check=True)
    pid = _parent(db, file_info_factory, pwd)
    result = ArchiveIndexer(db).index_archive(pid, str(pwd))
    assert result.status == ArchiveStatus.PASSWORD_REQUIRED.value
    assert db.get_archive_members(pid) == []


def test_unicode_and_case_collisions_kept_distinct(db, file_info_factory, tmp_path: Path) -> None:
    archive = tmp_path / "u.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("A.txt", "upper")
        zf.writestr("a.txt", "lower")
        zf.writestr("éàü/ñ.txt", "unicode")
    pid = _parent(db, file_info_factory, archive)
    ArchiveIndexer(db).index_archive(pid, str(archive))
    paths = sorted(m["archive_member_path"] for m in db.get_archive_members(pid))
    assert paths == ["A.txt", "a.txt", "éàü/ñ.txt"]


def test_restart_persistence_and_restore(db, file_info_factory, tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("persist.txt", "persistent content")
    pid = _parent(db, file_info_factory, archive)
    ArchiveIndexer(db).index_archive(pid, str(archive))

    # simulate delete then restore
    db.mark_archive_members_missing(pid)
    assert db.get_archive_members(pid) == []
    ArchiveIndexer(db).index_archive(pid, str(archive), force=True)
    assert {m["archive_member_path"] for m in db.get_archive_members(pid)} == {"persist.txt"}

    # reopen the database (restart) and confirm persistence + FTS
    reopened = DatabaseManager(db.db_path)
    rows = reopened.search_files("persistent")
    assert any(r["filename"] == "persist.txt" for r in rows)
