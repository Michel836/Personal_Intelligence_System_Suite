"""Contract tests for the scanner ``FileInfo`` model."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.scanner.models import FileInfo


def test_file_info_requires_created_and_modified_timestamps() -> None:
    """Filesystem timestamps are mandatory; callers must supply them."""
    with pytest.raises(ValidationError) as excinfo:
        FileInfo(path=Path("x.txt"), filename="x.txt", extension=".txt", size_bytes=1)

    missing = {error["loc"][0] for error in excinfo.value.errors()}
    assert missing == {"created_at", "modified_at"}
