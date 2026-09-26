"""Shared pytest fixtures for the test suite.

The scanner :class:`~src.scanner.models.FileInfo` requires filesystem
timestamps. Tests should construct instances through :func:`make_file_info` so
they stay schema-valid and deterministic instead of re-inventing constructor
calls (and drifting from the model).

Note: ``FileInfo`` belongs to the scanner model and does **not** carry
``content_text``; extracted content is persisted separately through
``DatabaseManager.update_content``.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytest

from src.scanner.models import FileInfo, FileType, Priority

# Deterministic, timezone-naive timestamps so assertions never depend on "now".
FIXED_CREATED_AT = datetime(2024, 1, 1, 12, 0, 0)
FIXED_MODIFIED_AT = datetime(2024, 1, 2, 12, 0, 0)


def make_file_info(
    path: str | Path,
    *,
    filename: str | None = None,
    extension: str | None = None,
    size_bytes: int = 0,
    file_type: FileType = FileType.OTHER,
    priority: Priority = Priority.MEDIUM,
    created_at: datetime | None = None,
    modified_at: datetime | None = None,
    accessed_at: datetime | None = None,
    **extra: Any,
) -> FileInfo:
    """Build a schema-valid ``scanner.models.FileInfo``.

    Required filesystem timestamps are always supplied (deterministically), so
    callers only need to describe the file itself.
    """
    path = Path(path)
    return FileInfo(
        path=path,
        filename=filename if filename is not None else path.name,
        extension=extension if extension is not None else path.suffix,
        size_bytes=size_bytes,
        created_at=created_at if created_at is not None else FIXED_CREATED_AT,
        modified_at=modified_at if modified_at is not None else FIXED_MODIFIED_AT,
        accessed_at=accessed_at,
        file_type=file_type,
        priority=priority,
        **extra,
    )


@pytest.fixture
def file_info_factory() -> Callable[..., FileInfo]:
    """Return the :func:`make_file_info` helper for use in tests."""
    return make_file_info
