"""M014 integration: exact/version freshness under controlled sandbox mutations."""
from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.dedup import ContentHasher, DedupStore, ExactDuplicateEngine, VersionTracker


def _id(db, path: Path) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM files WHERE path=?", (str(path),)).fetchone()[0])


def test_exact_and_version_freshness_under_mutation(tmp_path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.txt").write_text("shared body " * 40)
    (root / "a_copy.txt").write_text("shared body " * 40)
    (root / "same_size_but_diff.txt").write_text("x" * (root / "a.txt").stat().st_size)
    (root / "rapport_v1.txt").write_text("rapport version one " * 20)
    (root / "rapport_v2.txt").write_text("rapport version two " * 20)

    db = DatabaseManager(tmp_path / "db.db")
    service = ScanService(db)
    service.run(ScanRequest(root=root, batch_size=100))

    store = DedupStore(db)
    hasher = ContentHasher(db, store)
    exact = ExactDuplicateEngine(db, store, hasher)
    hasher.backfill(min_size=1)
    groups = exact.groups(min_size=1)
    assert len(groups) == 1
    assert {m["filename"] for m in groups[0]["members"]} == {"a.txt", "a_copy.txt"}

    tracker = VersionTracker(db, store)
    tracker.build()
    fam = tracker.family_for_file(_id(db, root / "rapport_v2.txt"))
    assert fam is not None and fam["confidence"] == "HIGH"

    # 1. content change invalidates the hash and breaks the exact group.
    a_copy = root / "a_copy.txt"
    a_copy.write_text("now different content " * 30)
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET size_bytes=?, modified_at=? WHERE path=?",
                     (a_copy.stat().st_size, "2026-06-01 00:00:00", str(a_copy)))
        conn.commit()
    assert any(s["id"] == _id(db, a_copy) for s in store.stale_hash_targets(min_size=1))
    hasher.backfill(min_size=1)
    assert exact.groups(min_size=1) == []

    # 2. delete a version -> a lone member is no longer a family.
    (root / "rapport_v1.txt").unlink()
    service.run(ScanRequest(root=root, batch_size=100))
    tracker.build()
    assert tracker.family_for_file(_id(db, root / "rapport_v2.txt")) is None

    # 3. re-add it -> family restored.
    (root / "rapport_v1.txt").write_text("rapport version one " * 20)
    service.run(ScanRequest(root=root, batch_size=100))
    tracker.build()
    assert tracker.family_for_file(_id(db, root / "rapport_v2.txt")) is not None

    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        dup = conn.execute(
            "SELECT COUNT(*) FROM (SELECT path FROM files GROUP BY path HAVING COUNT(*)>1)"
        ).fetchone()[0]
    assert dup == 0
