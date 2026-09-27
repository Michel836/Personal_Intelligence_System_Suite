"""Archive-specific hostile/adversarial tests (M009J.25)."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.archives.indexer import ArchiveIndexer
from src.archives.inspector import ArchiveInspector, ArchiveLimitError, ArchiveStatus, MemberType
from src.archives.limits import ArchiveLimits
from src.core.database import DatabaseManager
from src.scanner.models import FileType

LIM = ArchiveLimits(max_members=1000, max_member_bytes=10 * 1024 * 1024,
                    max_total_uncompressed=50 * 1024 * 1024, max_ratio=200, timeout=10)


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "hostile.db")


def _zip(path: Path, entries) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, d in entries:
            zf.writestr(n, d)
    return path


def test_backslash_and_unicode_names_stay_inside(tmp_path: Path) -> None:
    p = _zip(tmp_path / "names.zip", [
        ("a\\..\\..\\evil.txt", "x"),
        ("\u202eexe.txt", "rtl override"),
        ("..\\..\\up.txt", "y"),
        ("normal\\nested.txt", "ok"),
    ])
    members, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.OK
    # every accepted path is relative, non-empty and has no traversal segment
    for m in members:
        assert not m.member_path.startswith("/")
        assert ".." not in m.member_path.split("/")
    assert all("\\" not in m.member_path for m in members)


def test_forged_member_name_read_is_contained(tmp_path: Path) -> None:
    p = _zip(tmp_path / "a.zip", [("real.txt", "content")])
    fake = next(iter(ArchiveInspector(p, limits=LIM).list_members()[0]))
    from src.archives.inspector import ArchiveMember

    bogus = ArchiveMember(member_path="nothere", raw_name="nothere",
                          member_type=MemberType.FILE, uncompressed_size=1)
    with pytest.raises(ArchiveLimitError) as exc:
        ArchiveInspector(p, limits=LIM).open_member(bogus)
    assert exc.value.status in {ArchiveStatus.CORRUPT_ARCHIVE, ArchiveStatus.UNSUPPORTED_FORMAT}


def test_hardlink_is_metadata_only(tmp_path: Path) -> None:
    import io
    import tarfile

    p = tmp_path / "links.tar"
    with tarfile.open(p, "w") as tf:
        target = tarfile.TarInfo("target.txt")
        target.size = 3
        tf.addfile(target, io.BytesIO(b"abc"))
        link = tarfile.TarInfo("hard")
        link.type = tarfile.LNKTYPE
        link.linkname = "target.txt"
        tf.addfile(link)
    members, _ = ArchiveInspector(p, limits=LIM).list_members()
    hard = next(m for m in members if m.member_path == "hard")
    assert hard.member_type is MemberType.HARDLINK
    with pytest.raises(ArchiveLimitError):
        ArchiveInspector(p, limits=LIM).open_member(hard)


def test_partial_then_resume_extraction(db, file_info_factory, tmp_path: Path) -> None:
    archive = _zip(tmp_path / "a.zip", [("one.txt", "first content"), ("two.txt", "second content")])
    pid = db.save_file(file_info_factory(archive, size_bytes=archive.stat().st_size, file_type=FileType.ARCHIVE))
    # metadata-only pass (simulates a crash before extraction)
    ArchiveIndexer(db).index_archive(pid, str(archive), extract=False)
    assert all(not m["content_extracted"] for m in db.get_archive_members(pid))
    # resume with extraction; unchanged parent would normally skip, so force
    ArchiveIndexer(db).index_archive(pid, str(archive), extract=True, force=True)
    assert all(m["content_extracted"] for m in db.get_archive_members(pid))


def test_empty_and_zero_length_members(db, file_info_factory, tmp_path: Path) -> None:
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("empty.txt", "")
        zf.writestr("dir/", "")
    pid = db.save_file(file_info_factory(archive, size_bytes=archive.stat().st_size, file_type=FileType.ARCHIVE))
    result = ArchiveIndexer(db).index_archive(pid, str(archive))
    assert result.status == ArchiveStatus.OK.value
    states = {m["archive_member_path"]: m["extraction_state"] for m in db.get_archive_members(pid)}
    assert "empty.txt" in states
