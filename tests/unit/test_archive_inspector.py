"""Unit tests for the safe archive inspector (M009J.7-.12)."""
from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from src.archives.inspector import (
    ArchiveFormat,
    ArchiveInspector,
    ArchiveStatus,
    MemberType,
    detect_format,
    sanitize_member_path,
    virtual_path,
)
from src.archives.limits import ArchiveLimits

SEVENZIP = shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")

SMALL = ArchiveLimits(max_members=1000, max_member_bytes=10 * 1024 * 1024,
                      max_total_uncompressed=100 * 1024 * 1024, max_ratio=1000, timeout=30)


# --- path safety -----------------------------------------------------------

@pytest.mark.parametrize("unsafe", [
    "../evil", "../../escape", "/absolute/path", "C:\\Windows\\file",
    "\\\\server\\share", "folder/../../../outside", "a/../../b", "", "   ",
    "dir/\x00file",
])
def test_unsafe_member_paths_rejected(unsafe: str) -> None:
    assert sanitize_member_path(unsafe) is None


@pytest.mark.parametrize("raw,expected", [
    ("ok/path.txt", "ok/path.txt"),
    ("a/./b.txt", "a/b.txt"),
    ("dir/", "dir"),
    ("nested/deep/file.pdf", "nested/deep/file.pdf"),
    ("back\\slash\\x.txt", "back/slash/x.txt"),
    ("éàü/rapport.txt", "éàü/rapport.txt"),
])
def test_safe_member_paths_normalized(raw: str, expected: str) -> None:
    assert sanitize_member_path(raw) == expected


def test_virtual_path_is_unambiguous() -> None:
    assert virtual_path("/a/b.zip", "c/d.txt") == "/a/b.zip!/c/d.txt"


# --- detection -------------------------------------------------------------

def test_detect_format_by_extension_and_magic(tmp_path: Path) -> None:
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("x", "y")
    assert detect_format(z) is ArchiveFormat.ZIP
    assert detect_format(tmp_path / "a.tar.gz") is ArchiveFormat.TAR_GZ
    assert detect_format(tmp_path / "a.tgz") is ArchiveFormat.TAR_GZ
    assert detect_format(tmp_path / "a.tar.bz2") is ArchiveFormat.TAR_BZ2
    assert detect_format(tmp_path / "a.tar.xz") is ArchiveFormat.TAR_XZ
    assert detect_format(tmp_path / "a.7z") is ArchiveFormat.SEVENZIP
    assert detect_format(tmp_path / "a.rar") is ArchiveFormat.RAR


# --- zip -------------------------------------------------------------------

def _zip(tmp_path: Path, name: str, mapping) -> Path:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        for k, v in mapping:
            zf.writestr(k, v)
    return p


def test_zip_members_and_read(tmp_path: Path) -> None:
    p = _zip(tmp_path, "a.zip", [
        ("docs/report.txt", "hello"),
        ("dir/", ""),
        ("dup/a.txt", "1"),
        ("dup/a.txt", "2"),
        ("unicode/éàü.txt", "u"),
    ])
    members, status = ArchiveInspector(p, limits=SMALL).list_members()
    assert status is ArchiveStatus.OK
    paths = [m.member_path for m in members]
    assert "docs/report.txt" in paths
    assert paths.count("dup/a.txt") == 2  # duplicate basenames retained
    rep = next(m for m in members if m.member_path == "docs/report.txt")
    assert ArchiveInspector(p, limits=SMALL).open_member(rep).read() == b"hello"


def test_zip_slip_members_excluded(tmp_path: Path) -> None:
    p = _zip(tmp_path, "slip.zip", [
        ("../evil", "x"), ("../../escape", "x"), ("/abs", "x"),
        ("C:\\win", "x"), ("\\\\srv\\share", "x"), ("folder/../../../outside", "x"),
        ("safe.txt", "ok"),
    ])
    members, status = ArchiveInspector(p, limits=SMALL).list_members()
    assert status is ArchiveStatus.OK
    assert [m.member_path for m in members] == ["safe.txt"]


def test_zip_truncated_is_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "bad.zip"
    p.write_bytes(b"PK\x03\x04garbage")
    members, status = ArchiveInspector(p, limits=SMALL).list_members()
    assert status is ArchiveStatus.CORRUPT_ARCHIVE
    assert members == []


# --- tar family ------------------------------------------------------------

def _tar(tmp_path: Path, name: str, mode: str, payload: bytes) -> Path:
    p = tmp_path / name
    with tarfile.open(p, mode) as tf:
        ti = tarfile.TarInfo("docs/a.txt")
        ti.size = len(payload)
        tf.addfile(ti, io.BytesIO(payload))
        sym = tarfile.TarInfo("link")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "/etc/passwd"
        tf.addfile(sym)
    return p


@pytest.mark.parametrize("name,mode", [
    ("a.tar", "w"), ("a.tar.gz", "w:gz"), ("a.tar.bz2", "w:bz2"),
])
def test_tar_family(tmp_path: Path, name: str, mode: str) -> None:
    p = _tar(tmp_path, name, mode, b"tar payload")
    members, status = ArchiveInspector(p, limits=SMALL).list_members()
    assert status is ArchiveStatus.OK
    link = next(m for m in members if m.member_path == "link")
    assert link.member_type is MemberType.SYMLINK
    a = next(m for m in members if m.member_path == "docs/a.txt")
    assert ArchiveInspector(p, limits=SMALL).open_member(a).read() == b"tar payload"


def test_tar_symlink_never_followed(tmp_path: Path) -> None:
    p = _tar(tmp_path, "a.tar", "w", b"d")
    members, _ = ArchiveInspector(p, limits=SMALL).list_members()
    link = next(m for m in members if m.member_type is MemberType.SYMLINK)
    from src.archives.inspector import ArchiveLimitError

    with pytest.raises(ArchiveLimitError):
        ArchiveInspector(p, limits=SMALL).open_member(link)


# --- limits ----------------------------------------------------------------

def test_member_count_limit(tmp_path: Path) -> None:
    p = _zip(tmp_path, "many.zip", [(f"f{i}.txt", "x") for i in range(50)])
    _, status = ArchiveInspector(p, limits=ArchiveLimits(max_members=10)).list_members()
    assert status is ArchiveStatus.LIMIT_MEMBER_COUNT


def test_member_size_limit(tmp_path: Path) -> None:
    p = _zip(tmp_path, "big.zip", [("big.txt", "A" * 100000)])
    members, status = ArchiveInspector(p, limits=ArchiveLimits(max_member_bytes=1024)).list_members()
    assert status is ArchiveStatus.LIMIT_MEMBER_SIZE


def test_total_size_limit(tmp_path: Path) -> None:
    p = _zip(tmp_path, "total.zip", [(f"f{i}.txt", "A" * 5000) for i in range(10)])
    limits = ArchiveLimits(max_member_bytes=10 * 1024 * 1024, max_total_uncompressed=12000)
    _, status = ArchiveInspector(p, limits=limits).list_members()
    assert status is ArchiveStatus.LIMIT_TOTAL_SIZE


def test_compression_ratio_limit(tmp_path: Path) -> None:
    p = _zip(tmp_path, "bomb.zip", [("z.txt", "\x00" * 3_000_000)])
    limits = ArchiveLimits(max_member_bytes=50 * 1024 * 1024, max_total_uncompressed=50 * 1024 * 1024,
                           max_ratio=50)
    _, status = ArchiveInspector(p, limits=limits).list_members()
    assert status is ArchiveStatus.LIMIT_COMPRESSION_RATIO


def test_unsupported_and_unknown(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    _, status = ArchiveInspector(p, limits=SMALL).list_members()
    assert status is ArchiveStatus.UNSUPPORTED_FORMAT


def test_bare_gz_and_bz2(tmp_path: Path) -> None:
    import bz2
    import gzip

    g = tmp_path / "g.txt.gz"
    g.write_bytes(gzip.compress(b"gzip payload"))
    members, status = ArchiveInspector(g, limits=SMALL).list_members()
    assert status is ArchiveStatus.OK and members[0].member_path == "g.txt"
    assert ArchiveInspector(g, limits=SMALL).open_member(members[0]).read() == b"gzip payload"

    b = tmp_path / "b.txt.bz2"
    b.write_bytes(bz2.compress(b"bz2 payload"))
    m2, s2 = ArchiveInspector(b, limits=SMALL).list_members()
    assert s2 is ArchiveStatus.OK
    assert ArchiveInspector(b, limits=SMALL).open_member(m2[0]).read() == b"bz2 payload"


# --- 7z / rar --------------------------------------------------------------

@pytest.mark.skipif(SEVENZIP is None, reason="no 7z backend")
def test_sevenzip_plain_and_password(tmp_path: Path) -> None:
    f = tmp_path / "note.txt"
    f.write_text("seven zip content")
    plain = tmp_path / "plain.7z"
    subprocess.run([SEVENZIP, "a", "-t7z", str(plain), str(f)], capture_output=True, check=True)
    members, status = ArchiveInspector(plain, limits=SMALL).list_members()
    assert status is ArchiveStatus.OK
    assert ArchiveInspector(plain, limits=SMALL).open_member(members[0]).read() == b"seven zip content"

    pwd = tmp_path / "pwd.7z"
    subprocess.run([SEVENZIP, "a", "-t7z", "-psecret", str(pwd), str(f)], capture_output=True, check=True)
    _, status2 = ArchiveInspector(pwd, limits=SMALL).list_members()
    assert status2 is ArchiveStatus.PASSWORD_REQUIRED


def test_rar_backend_unavailable_is_explicit(tmp_path: Path, monkeypatch) -> None:
    import src.archives.inspector as insp

    monkeypatch.setattr(insp, "_rar_backend_available", lambda: False)
    p = tmp_path / "a.rar"
    # minimal RAR4 signature so format detection reports RAR
    p.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 32)
    _, status = ArchiveInspector(p, limits=SMALL).list_members()
    assert status in {ArchiveStatus.BACKEND_UNAVAILABLE, ArchiveStatus.PASSWORD_REQUIRED}


def test_rar_without_signature_is_classified(tmp_path: Path, monkeypatch) -> None:
    import src.archives.inspector as insp

    monkeypatch.setattr(insp, "_rar_backend_available", lambda: True)
    # No archive signature at all -> NOT_ARCHIVE_FORMAT, not "corrupt".
    p = tmp_path / "not.rar"
    p.write_bytes(b"not a rar archive at all" * 8)
    _, status = ArchiveInspector(p, limits=SMALL).list_members()
    assert status is ArchiveStatus.NOT_ARCHIVE_FORMAT
