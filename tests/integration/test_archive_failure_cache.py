"""M011: deterministic archive outcomes are cached; transient ones are not."""
from __future__ import annotations

from pathlib import Path

from src.archives.indexer import ArchiveIndexer
from src.archives.inspector import ArchiveInspector, ArchiveLimits, ArchiveStatus
from src.archives.limits import ArchivePolicy
from src.core.database import DatabaseManager
from src.scanner.models import FileInfo, FileType, Priority


def _parent(db: DatabaseManager, path: Path, *, archive=True) -> int:
    fi = FileInfo(
        path=path, filename=path.name, size_bytes=path.stat().st_size,
        modified_at=__import__("datetime").datetime(2026, 1, 1),
        extension=path.suffix, file_type=FileType.ARCHIVE if archive else FileType.OTHER,
        priority=Priority.MEDIUM,
    )
    return db.save_file(fi)


def _index(db: DatabaseManager, pid: int, path: Path, **kw):
    return ArchiveIndexer(db, **kw).index_archive(pid, str(path))


def test_corrupt_archive_is_not_reprocessed_when_unchanged(tmp_path, monkeypatch) -> None:
    p = tmp_path / "corrupt.zip"
    p.write_bytes(b"PK\x03\x04garbage")
    db = DatabaseManager(tmp_path / "db.db")
    pid = _parent(db, p)

    calls = {"n": 0}
    original = ArchiveInspector.list_members

    def spy(self):
        calls["n"] += 1
        return original(self)

    monkeypatch.setattr(ArchiveInspector, "list_members", spy)

    first = _index(db, pid, p)
    assert first.status == ArchiveStatus.CORRUPT_ARCHIVE.value
    assert calls["n"] == 1

    second = _index(db, pid, p)
    assert second.unchanged is True
    assert second.status == ArchiveStatus.CORRUPT_ARCHIVE.value
    assert calls["n"] == 1, "corrupt archive must not be re-listed while unchanged"


def test_not_archive_format_is_cached(tmp_path, monkeypatch) -> None:
    p = tmp_path / "proprietary.zip"
    p.write_bytes(b"\x89C2F" + b"\x00" * 64)
    db = DatabaseManager(tmp_path / "db.db")
    pid = _parent(db, p)

    calls = {"n": 0}
    original = ArchiveInspector.list_members
    monkeypatch.setattr(ArchiveInspector, "list_members",
                        lambda self: (calls.__setitem__("n", calls["n"] + 1), original(self))[1])

    first = _index(db, pid, p)
    assert first.status == ArchiveStatus.NOT_ARCHIVE_FORMAT.value
    second = _index(db, pid, p)
    assert second.unchanged is True and second.status == ArchiveStatus.NOT_ARCHIVE_FORMAT.value
    assert calls["n"] == 1


def test_fingerprint_change_reprocesses(tmp_path, monkeypatch) -> None:
    import os
    import time

    p = tmp_path / "corrupt.zip"
    p.write_bytes(b"PK\x03\x04garbage")
    db = DatabaseManager(tmp_path / "db.db")
    pid = _parent(db, p)

    calls = {"n": 0}
    original = ArchiveInspector.list_members
    monkeypatch.setattr(ArchiveInspector, "list_members",
                        lambda self: (calls.__setitem__("n", calls["n"] + 1), original(self))[1])

    _index(db, pid, p)
    assert calls["n"] == 1
    time.sleep(0.01)
    p.write_bytes(b"PK\x03\x04different garbage")
    os.utime(p, None)
    db.save_file(FileInfo(
        path=p, filename=p.name, size_bytes=p.stat().st_size,
        modified_at=__import__("datetime").datetime(2026, 1, 2),
        extension=p.suffix, file_type=FileType.ARCHIVE, priority=Priority.MEDIUM,
    ))
    second = _index(db, pid, p)
    assert second.unchanged is False
    assert calls["n"] == 2


def test_limit_change_reprocesses(tmp_path, monkeypatch) -> None:
    p = tmp_path / "many.zip"
    import zipfile

    with zipfile.ZipFile(p, "w") as zf:
        for i in range(20):
            zf.writestr(f"f{i}.txt", "x")
    db = DatabaseManager(tmp_path / "db.db")
    pid = _parent(db, p)

    first = ArchiveIndexer(db, limits=ArchiveLimits(max_members=100)).index_archive(pid, str(p))
    assert first.status == ArchiveStatus.OK.value
    # A stricter limit changes the cache token -> must re-process.
    second = ArchiveIndexer(db, limits=ArchiveLimits(max_members=5)).index_archive(pid, str(p))
    assert second.unchanged is False
    assert second.status == ArchiveStatus.LIMIT_MEMBER_COUNT.value


def test_transient_backend_unavailable_is_not_cached(tmp_path, monkeypatch) -> None:
    import src.archives.inspector as insp

    monkeypatch.setattr(insp, "_rar_backend_available", lambda: False)
    p = tmp_path / "a.rar"
    p.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 64)
    db = DatabaseManager(tmp_path / "db.db")
    pid = _parent(db, p)

    first = ArchiveIndexer(db, policy=ArchivePolicy(enabled=True)).index_archive(pid, str(p))
    assert first.status == ArchiveStatus.BACKEND_UNAVAILABLE.value
    # Transient: not cached, so it is re-attempted on the next pass.
    second = ArchiveIndexer(db, policy=ArchivePolicy(enabled=True)).index_archive(pid, str(p))
    assert second.unchanged is False
