from datetime import datetime
from pathlib import Path

import pytest

from src.scanner.models import FileInfo, normalize_filesystem_identity


def test_unsigned_inode_maps_to_signed_sqlite_int64() -> None:
    raw_inode = 11389491324472828734
    expected = raw_inode - (1 << 64)

    assert normalize_filesystem_identity(raw_inode) == expected
    assert -(1 << 63) <= expected <= (1 << 63) - 1


def test_fileinfo_normalizes_portal_inode() -> None:
    raw_inode = 11389491324472828734
    info = FileInfo(
        path=Path("/run/user/1000/doc/example.mp4"),
        filename="example.mp4",
        size_bytes=123,
        modified_at=datetime(2026, 9, 28, 14, 51, 53),
        extension=".mp4",
        device_id=42,
        inode=raw_inode,
    )

    assert info.device_id == 42
    assert info.inode == raw_inode - (1 << 64)


def test_identity_values_already_in_sqlite_range_are_unchanged() -> None:
    assert normalize_filesystem_identity(0) == 0
    assert normalize_filesystem_identity((1 << 63) - 1) == (1 << 63) - 1
    assert normalize_filesystem_identity(-(1 << 63)) == -(1 << 63)
    assert normalize_filesystem_identity(None) is None


def test_identity_outside_uint64_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_filesystem_identity(1 << 64)
