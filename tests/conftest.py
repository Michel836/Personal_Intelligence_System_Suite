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

from dataclasses import dataclass
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


@dataclass
class GalaxyEnv:
    """Synthetic, fully local galaxy fixture (no real corpus, no private text)."""

    db: Any
    store: Any
    service: Any
    ids: list[int]
    base_dir: Path


#: Five distinct synthetic themes; safe, non-private vocabulary only.
_GALAXY_THEMES: dict[str, str] = {
    "finance": "invoice bank payment accounting revenue tax budget audit ledger quarterly",
    "technology": "software machine learning compiler algorithm network data python testing",
    "legal": "contract clause court regulation compliance liability agreement statute",
    "health": "patient clinical diagnosis treatment medical hospital therapy research",
    "career": "resume candidate interview recruitment salary position employer skills",
}
_DIM = 16


def _build_galaxy_env(tmp_path: Path) -> GalaxyEnv:
    import numpy as np

    from src.core.database import DatabaseManager
    from src.galaxy import GalaxyService
    from src.intelligence.embedding_store import EmbeddingMatrixStore

    db = DatabaseManager(tmp_path / "galaxy.db")
    themes = list(_GALAXY_THEMES)
    rows: list[tuple[int, str, str]] = []
    fid = 0
    for theme in themes:
        for _ in range(6):
            fid += 1
            text = f"{_GALAXY_THEMES[theme]} {theme} document number {fid}"
            rows.append((fid, f"/synthetic/{theme}/{fid}.txt", text))
    # One exact-duplicate pair and one version pair for collapse coverage.
    rows.append((fid + 1, "/synthetic/legal/dup-a.txt", rows[12][2]))
    rows.append((fid + 2, "/synthetic/legal/dup-b.txt", rows[12][2]))
    rows.append((fid + 3, "/synthetic/report-v1.txt",
                 "quarterly finance report draft version one accounting revenue bank"))
    rows.append((fid + 4, "/synthetic/report-v2.txt",
                 "quarterly finance report final version two accounting revenue bank"))
    with db.get_connection() as conn:
        for i, path, _text in rows:
            conn.execute(
                "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
                "state, document_kind, content_extracted) VALUES (?, ?, ?, '.txt', 100, "
                "'2024-01-15', 'ACTIVE', 'PHYSICAL_FILE', 1)",
                (i, path, Path(path).name))
        conn.commit()
    for i, _path, text in rows:
        db.update_content(i, text)
    # Give the duplicate pair a shared digest and the version pair a family.
    from src.dedup import DedupStore
    dedup = DedupStore(db)
    dedup.set_hash(fid + 1, digest="deadbeefcafe", size_bytes=100, modified_at="2024-01-15", state="OK")
    dedup.set_hash(fid + 2, digest="deadbeefcafe", size_bytes=100, modified_at="2024-01-15", state="OK")
    dedup.replace_version_families([{
        "family_key": "version:report", "base_name": "report", "directory": "/synthetic",
        "confidence": "HIGH",
        "members": [{"id": fid + 3, "rank": 0, "is_primary": 0, "confidence": "HIGH"},
                    {"id": fid + 4, "rank": 1, "is_primary": 1, "confidence": "HIGH"}],
    }])
    rng = np.random.default_rng(0)
    ids = [i for i, _p, _t in rows]
    matrix = np.zeros((len(ids), _DIM), dtype=np.float32)
    for row, (_i, _path, _text) in enumerate(rows):
        vec = rng.normal(0, 0.02, _DIM).astype(np.float32)
        theme = _path.split("/")[2] if _path.count("/") >= 2 else "report"
        if theme in themes:
            vec[themes.index(theme)] = 1.0
        matrix[row] = vec
    base_dir = tmp_path / "store"
    store = EmbeddingMatrixStore("synthetic", "synthetic", _DIM, base_dir=base_dir)
    store.save(ids, matrix, hashes=[str(i) for i in ids])
    service = GalaxyService(db, embedding_store=store)
    return GalaxyEnv(db=db, store=store, service=service, ids=ids, base_dir=base_dir)


@pytest.fixture
def galaxy_env(tmp_path: Path) -> GalaxyEnv:
    """Create an isolated synthetic corpus + embedding store for galaxy tests."""
    return _build_galaxy_env(tmp_path)
