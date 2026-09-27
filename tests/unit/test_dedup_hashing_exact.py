"""Exact-duplicate + content-hash contract tests (M014)."""
from __future__ import annotations

import datetime
from pathlib import Path

from src.core.database import DatabaseManager
from src.dedup import ContentHasher, DedupStore, ExactDuplicateEngine
from src.scanner.models import FileType

_NOW = datetime.datetime(2026, 1, 1, 12, 0, 0)


def _save(db: DatabaseManager, factory, path: Path, *, size=None, kind=FileType.OTHER):
    return db.save_file(factory(
        path, size_bytes=size if size is not None else path.stat().st_size,
        file_type=kind, modified_at=_NOW,
    ))


def test_size_first_hashing_and_exact_groups(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    engine = ExactDuplicateEngine(db, store)
    a = tmp_path / "a.txt"
    a.write_text("duplicate body " * 40)
    b = tmp_path / "b_copy.txt"
    b.write_text("duplicate body " * 40)
    c = tmp_path / "c.txt"
    c.write_text("x" * a.stat().st_size)  # same size, different bytes
    unique = tmp_path / "unique.txt"
    unique.write_text("a unique length that no one shares")
    ia = _save(db, file_info_factory, a)
    ib = _save(db, file_info_factory, b)
    ic = _save(db, file_info_factory, c)
    iu = _save(db, file_info_factory, unique)

    stats = engine.hash_duplicate_candidates(min_size=1)
    assert stats["ok"] >= 3
    # unique-size file must never be read/hashed
    assert store.get_hash(iu) is None
    groups = engine.groups(min_size=1)
    assert len(groups) == 1
    g = groups[0]
    assert {m["id"] for m in g["members"]} == {ia, ib}
    assert g["count"] == 2 and g["wasted_bytes"] == a.stat().st_size
    assert ic not in {m["id"] for m in g["members"]}


def test_hash_invalidated_on_content_change(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    hasher = ContentHasher(db, store)
    p = tmp_path / "f.txt"
    p.write_text("original " * 30)
    fid = _save(db, file_info_factory, p)
    hasher.backfill(min_size=1)
    assert store.get_hash(fid)["state"] == "OK"

    # Simulate an external content change with a new size/mtime (re-save row).
    p.write_text("changed content that is longer " * 30)
    _save(db, file_info_factory, p, size=p.stat().st_size)
    stale = store.stale_hash_targets(min_size=1)
    assert any(s["id"] == fid for s in stale)
    hasher.backfill(min_size=1)
    assert store.get_hash(fid)["size_bytes"] == p.stat().st_size


def test_zero_byte_and_physical_only(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    engine = ExactDuplicateEngine(db, store)
    z1 = tmp_path / "z1.empty"
    z1.write_bytes(b"")
    z2 = tmp_path / "z2.empty"
    z2.write_bytes(b"")
    _save(db, file_info_factory, z1)
    _save(db, file_info_factory, z2)
    engine.hash_duplicate_candidates(min_size=0)
    assert engine.groups(min_size=0)  # zero-byte files are duplicates of each other
    assert engine.groups(min_size=1) == []  # excluded by min-size threshold


def test_unreadable_file_is_recorded_not_crashing(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    hasher = ContentHasher(db, store)
    p = tmp_path / "ghost.txt"
    p.write_text("present at scan time " * 10)
    fid = _save(db, file_info_factory, p)
    p.unlink()  # disappeared before hashing
    stats = hasher.backfill(min_size=1)
    assert stats["unreadable"] == 1
    assert store.get_hash(fid)["state"] == "UNREADABLE"


def test_too_large_is_deterministic(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    hasher = ContentHasher(db, store, max_bytes=8)
    p = tmp_path / "big.bin"
    p.write_bytes(b"0123456789")
    fid = _save(db, file_info_factory, p)
    hasher.backfill(min_size=1)
    assert store.get_hash(fid)["state"] == "TOO_LARGE"


def test_exact_scope_filter(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    engine = ExactDuplicateEngine(db, store)
    sub = tmp_path / "keep"
    sub.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    a = sub / "a.txt"
    a.write_text("body " * 50)
    b = other / "b.txt"
    b.write_text("body " * 50)
    _save(db, file_info_factory, a)
    _save(db, file_info_factory, b)
    engine.hash_duplicate_candidates(min_size=1)
    assert len(engine.groups(min_size=1)) == 1
    # Scope = duplicates *within* the root (>= 2 members in scope).
    assert engine.groups(min_size=1, scope_prefix=str(sub)) == []
    scoped = engine.groups(min_size=1, scope_prefix=str(tmp_path))
    assert len(scoped) == 1 and all(m["path"].startswith(str(tmp_path)) for m in scoped[0]["members"])
