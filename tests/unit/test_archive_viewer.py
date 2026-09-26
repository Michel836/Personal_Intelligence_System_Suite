"""Tests for archive viewer helpers (M009J.17)."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.archives.indexer import ArchiveIndexer
from src.archives.viewer import (
    container_summary,
    human_size,
    list_container_members,
    member_detail,
)
from src.core.database import DatabaseManager
from src.scanner.models import FileType


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "viewer.db")


@pytest.fixture
def indexed(db: DatabaseManager, file_info_factory, tmp_path: Path):
    archive = tmp_path / "container.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/report.txt", "viewer preview content " * 500)
        zf.writestr("images/pic.png", "notreallypng")
    pid = db.save_file(file_info_factory(archive, size_bytes=archive.stat().st_size, file_type=FileType.ARCHIVE))
    ArchiveIndexer(db).index_archive(pid, str(archive))
    return pid


def test_container_summary(db, indexed) -> None:
    summary = container_summary(db, indexed)
    assert summary is not None
    assert summary["format"] == "ZIP"
    assert summary["status"] == "OK"
    assert summary["member_count"] == 2
    assert summary["active_member_count"] == 2
    assert summary["compressed_human"]
    assert summary["expanded_human"]


def test_list_members_bounded_and_paged(db, indexed) -> None:
    members = list_container_members(db, indexed, limit=1)
    assert len(members) == 1
    page2 = list_container_members(db, indexed, limit=1, offset=1)
    assert page2 and page2[0]["id"] != members[0]["id"]


def test_member_detail_preview_is_bounded(db, indexed) -> None:
    members = list_container_members(db, indexed)
    report = next(m for m in members if m["member_path"] == "docs/report.txt")
    detail = member_detail(db, report["id"], preview_chars=100)
    assert detail is not None
    assert detail["parent_name"] == "container.zip"
    assert detail["member_path"] == "docs/report.txt"
    assert detail["virtual_path"].endswith("!/docs/report.txt")
    assert len(detail["preview"]) == 100
    assert detail["preview_truncated"] is True


def test_member_detail_missing_returns_none(db) -> None:
    assert member_detail(db, 999999) is None
    assert container_summary(db, 999999) is None


@pytest.mark.parametrize("value,expected", [
    (0, "0 B"), (1023, "1023 B"), (2048, "2.0 KB"), (5 * 1024 * 1024, "5.0 MB"),
])
def test_human_size(value, expected) -> None:
    assert human_size(value) == expected
