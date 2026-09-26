"""Contract tests for the scanner ``FileInfo`` model."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.scanner.models import FileInfo, stat_created_at


def test_file_info_requires_modified_timestamp_but_not_created() -> None:
    """``modified_at`` is mandatory; ``created_at`` is optional.

    Birth time is not reliably available (on Linux ``st_ctime`` is inode
    change time), so callers may leave ``created_at`` unset.
    """
    with pytest.raises(ValidationError) as excinfo:
        FileInfo(path=Path("x.txt"), filename="x.txt", extension=".txt", size_bytes=1)

    missing = {error["loc"][0] for error in excinfo.value.errors()}
    assert missing == {"modified_at"}


def test_stat_created_at_ignores_ctime_on_linux() -> None:
    """A stat result without ``st_birthtime`` yields ``None``, never ctime."""

    class FakeStat:
        st_ctime = 1_600_000_000.0

    assert stat_created_at(FakeStat()) is None


def test_stat_created_at_uses_birthtime_when_available() -> None:
    class FakeStat:
        st_ctime = 1_600_000_000.0
        st_birthtime = 1_500_000_000.0

    created = stat_created_at(FakeStat())
    assert created is not None
    assert created.year == 2017
