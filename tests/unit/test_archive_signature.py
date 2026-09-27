"""M011: archive signature classification (extension vs real content)."""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from src.archives.inspector import (
    ArchiveFormat,
    ArchiveInspector,
    ArchiveLimits,
    ArchiveStatus,
    detect_archive_signature,
    detect_format,
)

LIM = ArchiveLimits()


def _ok_zip(tmp_path: Path, name="a.zip") -> Path:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("x.txt", "hello")
    return p


def test_valid_zip_is_ok(tmp_path: Path) -> None:
    p = _ok_zip(tmp_path)
    assert detect_archive_signature(p) == (ArchiveFormat.ZIP, None)
    members, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.OK and members


def test_proprietary_zip_is_not_archive_not_corrupt(tmp_path: Path) -> None:
    # The M010 real-corpus case: *.zip with proprietary \\x89C2F magic.
    p = tmp_path / "proprietary.zip"
    p.write_bytes(b"\x89C2F" + b"\x00" * 64)
    assert detect_archive_signature(p) == (ArchiveFormat.ZIP, ArchiveStatus.NOT_ARCHIVE_FORMAT)
    _, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.NOT_ARCHIVE_FORMAT


def test_html_named_zip_is_not_archive(tmp_path: Path) -> None:
    p = tmp_path / "page.zip"
    p.write_bytes(b"<html>\r\n<body>not an archive</body></html>")
    _, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.NOT_ARCHIVE_FORMAT


def test_mislabelled_7z_reports_extension_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "actually.7z.zip"
    p.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 64)
    fmt, status = detect_archive_signature(p)
    assert fmt is ArchiveFormat.SEVENZIP
    assert status is ArchiveStatus.EXTENSION_MISMATCH
    _, st = ArchiveInspector(p, limits=LIM).list_members()
    assert st is ArchiveStatus.EXTENSION_MISMATCH
    # Extension metadata is preserved separately from the detected format.
    assert detect_format(p) is ArchiveFormat.SEVENZIP


def test_truncated_pk_zip_is_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "trunc.zip"
    p.write_bytes(b"PK\x03\x04garbage")
    _, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.CORRUPT_ARCHIVE


def test_non_archive_extension_is_unsupported(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    assert detect_archive_signature(p) == (ArchiveFormat.UNKNOWN, None)
    _, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.UNSUPPORTED_FORMAT


def test_tar_header_probe_is_not_flagged_as_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "a.tar"
    with tarfile.open(p, "w") as tf:
        ti = tarfile.TarInfo("a.txt")
        ti.size = 3
        tf.addfile(ti, io.BytesIO(b"abc"))
    assert detect_archive_signature(p) == (ArchiveFormat.TAR, None)
    _, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.OK


def test_bare_gz_requires_magic(tmp_path: Path) -> None:
    p = tmp_path / "fake.gz"
    p.write_bytes(b"not gzip data at all")
    _, status = ArchiveInspector(p, limits=LIM).list_members()
    assert status is ArchiveStatus.NOT_ARCHIVE_FORMAT
