"""Persistence contract for extracted content (M013-C surrogate edge case).

PyPDF2 can emit lone surrogate code points from malformed PDFs. SQLite's UTF-8
adapter rejects them, which previously made ``update_content`` raise and lose a
successfully extracted document. The persistence boundary must sanitise instead.
"""
from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager


def _add(db: DatabaseManager, file_info_factory, name: str) -> int:
    return db.save_file(file_info_factory(name, size_bytes=10))


def test_update_content_sanitizes_lone_surrogates(tmp_path: Path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "content.db")
    file_id = _add(db, file_info_factory, "malformed.pdf")
    # A lone high surrogate (as produced by some malformed PDF text layers).
    hostile = "before\ud800after"
    db.update_content(file_id, hostile)
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT content_text, content_extracted FROM files WHERE id=?", (file_id,)
        ).fetchone()
    assert row is not None
    assert row["content_extracted"] == 1
    assert row["content_text"] is not None
    row["content_text"].encode("utf-8")  # must be persistable/encodable
    assert "before" in row["content_text"] and "after" in row["content_text"]


def test_update_content_keeps_valid_unicode(tmp_path: Path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "content2.db")
    file_id = _add(db, file_info_factory, "résumé.txt")
    valid = "café über résumé — naïve ✓"
    db.update_content(file_id, valid)
    with db.get_connection() as conn:
        stored = conn.execute(
            "SELECT content_text FROM files WHERE id=?", (file_id,)
        ).fetchone()["content_text"]
    assert stored == valid
