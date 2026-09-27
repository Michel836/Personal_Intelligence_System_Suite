"""M016 graph/timeline freshness under controlled mutations."""
from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.dedup import ContentHasher, DedupStore, ExactDuplicateEngine, VersionTracker
from src.graph import DocumentGraph, RelationService
from src.intel import IntelPipeline, IntelStore


def _id(db, path: Path) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM files WHERE path=?", (str(path),)).fetchone()[0])


def _set_content(db, fid, text):
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET content_text=?, content_extracted=1, indexed_at=? WHERE id=?",
                     (text, "2026-01-01 00:00:00", fid))
        conn.commit()


def test_relations_and_timeline_update_after_mutations(tmp_path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.txt").write_text("alpha shared body " * 30)
    (root / "b_copy.txt").write_text("alpha shared body " * 30)
    (root / "rapport_v1.txt").write_text("rapport version one " * 20)
    (root / "rapport_v2.txt").write_text("rapport version two " * 20)

    db = DatabaseManager(tmp_path / "db.db")
    ScanService(db).run(ScanRequest(root=root, batch_size=100))
    ds = DedupStore(db)
    store = IntelStore(db)
    for name in ("a.txt", "b_copy.txt", "rapport_v1.txt", "rapport_v2.txt"):
        _set_content(db, _id(db, root / name), (root / name).read_text())

    def rebuild():
        ExactDuplicateEngine(db, ds, ContentHasher(db, ds)).hash_duplicate_candidates(min_size=1)
        VersionTracker(db, ds).build()
        IntelPipeline(db, store=store).run(min_chars=10)

    rebuild()
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    g = DocumentGraph(db, intel_store=store, dedup_store=ds)
    a = _id(db, root / "a.txt")
    b = _id(db, root / "b_copy.txt")
    assert b in {r.target for r in svc.relations_for(a, types=["EXACT_DUPLICATE"])}

    # delete the copy -> exact relation must disappear and metadata pruned
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=?", (b,))
        conn.commit()
    rebuild()
    assert b not in {r.target for r in svc.relations_for(a, types=["EXACT_DUPLICATE"])}
    assert store.get_language(b) is None

    # restore -> relation returns
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='ACTIVE' WHERE id=?", (b,))
        conn.commit()
    rebuild()
    assert b in {r.target for r in svc.relations_for(a, types=["EXACT_DUPLICATE"])}

    # timeline is consistent with lifecycle and never shows missing rows by default
    events = g.timeline_events(group="year")
    assert all(e["state"] == "ACTIVE" for e in events["events"])
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        dup = conn.execute("SELECT COUNT(*) FROM (SELECT path FROM files GROUP BY path HAVING COUNT(*)>1)").fetchone()[0]
    assert dup == 0


def test_entity_relation_refreshes_on_content_change(tmp_path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "x.txt").write_text("ACME GmbH invoice " * 20)
    (root / "y.txt").write_text("ACME GmbH contract " * 20)
    db = DatabaseManager(tmp_path / "db.db")
    ScanService(db).run(ScanRequest(root=root, batch_size=100))
    ds = DedupStore(db)
    store = IntelStore(db)
    for name in ("x.txt", "y.txt"):
        _set_content(db, _id(db, root / name), (root / name).read_text())
    IntelPipeline(db, store=store).run(min_chars=10)
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    x = _id(db, root / "x.txt")
    assert svc.relations_for(x, types=["SAME_ENTITY"])

    # remove the shared entity from y -> relation disappears after refresh
    _set_content(db, _id(db, root / "y.txt"), "unrelated text without the company " * 20)
    IntelPipeline(db, store=store).run(min_chars=10)
    rels = [r for r in svc.relations_for(x, types=["SAME_ENTITY"]) if r.target == _id(db, root / "y.txt")]
    assert rels == []
