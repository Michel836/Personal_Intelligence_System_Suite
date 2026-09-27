"""Content invalidation + archive-member cascade regression (M010 scale trial).

Two scale defects were found on real data:

1. A modified physical file kept its old ``content_text``/``content_extracted``
   forever, so FTS and embeddings served stale content.
2. Deleting an archive container marked only the parent MISSING; its virtual
   members stayed ACTIVE and surfaced as stale hits (including nested members).
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.archives.indexer import ArchiveIndexer
from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.core.volume import VolumeInfo


def _volume(tmp_path: Path) -> VolumeInfo:
    return VolumeInfo(stable_key="INV", device="INV", mountpoint=str(tmp_path), is_available=True)


def _scan(db: DatabaseManager, root: Path, tmp_path: Path):
    res = ScanService(db).run(ScanRequest(root=root, batch_size=100, volume=_volume(tmp_path)))
    assert res.status == "COMPLETED", (res.status, res.error)
    return res


def _file_row(db: DatabaseManager, path: Path):
    with db.get_connection() as conn:
        return conn.execute("SELECT * FROM files WHERE path = ?", (str(path),)).fetchone()


def test_modified_file_content_is_invalidated_and_refreshed(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    doc = root / "note.txt"
    doc.write_text("ORIGINALTOKEN " * 20, encoding="utf-8")
    db = DatabaseManager(tmp_path / "inv.db")
    _scan(db, root, tmp_path)
    db.update_content(_file_row(db, doc)["id"], "ORIGINALTOKEN " * 20)

    # Unchanged rescan must preserve extracted content.
    _scan(db, root, tmp_path)
    assert _file_row(db, doc)["content_extracted"] == 1

    # Modified file (new size + mtime) must invalidate stale content.
    doc.write_text("CHANGEDTOKEN " * 40, encoding="utf-8")
    _scan(db, root, tmp_path)
    row = _file_row(db, doc)
    assert row["content_extracted"] == 0
    assert row["content_text"] is None
    # The FTS index must drop the stale text.
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM files_fts WHERE files_fts MATCH 'ORIGINALTOKEN'").fetchone()[0] == 0


def test_missing_archive_container_cascades_to_nested_members(tmp_path: Path) -> None:
    import io

    root = tmp_path / "corpus"
    root.mkdir()
    archive = root / "box.zip"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zi:
        zi.writestr("c.txt", "nested content")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "top member")
        zf.writestr("inner.zip", inner.getvalue())

    db = DatabaseManager(tmp_path / "inv-arc.db")
    _scan(db, root, tmp_path)
    parent = _file_row(db, archive)
    ArchiveIndexer(db).index_archive(parent["id"], str(archive), extract=True)

    with db.get_connection() as conn:
        members = conn.execute(
            "SELECT id,state FROM files WHERE document_kind='ARCHIVE_MEMBER' AND archive_parent_id=?",
            (parent["id"],),
        ).fetchall()
    assert members and all(m["state"] == "ACTIVE" for m in members)

    archive.unlink()
    _scan(db, root, tmp_path)
    with db.get_connection() as conn:
        assert conn.execute("SELECT state FROM files WHERE id=?", (parent["id"],)).fetchone()[0] == "MISSING"
        child = conn.execute(
            "SELECT state FROM files WHERE document_kind='ARCHIVE_MEMBER' AND archive_parent_id=?",
            (parent["id"],),
        ).fetchall()
        assert child and all(r["state"] == "MISSING" for r in child)
        # Nested member (child of the inner archive member) must also be MISSING.
        nested = conn.execute(
            "SELECT state FROM files WHERE path LIKE ?", (f"{archive}!/inner.zip!/%",)
        ).fetchall()
        assert nested and all(r["state"] == "MISSING" for r in nested)
