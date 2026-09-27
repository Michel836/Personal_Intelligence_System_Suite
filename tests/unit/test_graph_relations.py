"""Relationship contract + bounded graph tests (M016)."""
from __future__ import annotations

import datetime
from pathlib import Path

from src.core.database import DatabaseManager
from src.dedup import ContentHasher, DedupStore, ExactDuplicateEngine, VersionTracker
from src.graph import DocumentGraph, RelationService, RelationType, to_networkx
from src.intel import IntelPipeline, IntelStore
from src.scanner.models import FileType


def _add(db, path: Path, content: str, *, mtime=None):
    path.write_text(content)
    from src.scanner.models import FileInfo
    fi = FileInfo(path=path, filename=path.name, size_bytes=path.stat().st_size,
                  modified_at=mtime or datetime.datetime(2026, 1, 1), extension=path.suffix,  # noqa: DTZ001
                  file_type=FileType.DOCUMENT)
    fid = db.save_file(fi)
    db.update_content(fid, content)
    return fid


def _fixture(tmp_path):
    db = DatabaseManager(tmp_path / "db.db")
    ds = DedupStore(db)
    ExactDuplicateEngine(db, ds, ContentHasher(db, ds)).hash_duplicate_candidates(min_size=1)
    a = _add(db, tmp_path / "a.txt", "shared body " * 50)
    b = _add(db, tmp_path / "b.txt", "shared body " * 50)
    c = _add(db, tmp_path / "rapport_v1.txt", "rapport version one " * 20)
    d = _add(db, tmp_path / "rapport_v2.txt", "rapport version two " * 20)
    ExactDuplicateEngine(db, ds, ContentHasher(db, ds)).hash_duplicate_candidates(min_size=1)
    VersionTracker(db, ds).build()
    store = IntelStore(db)
    IntelPipeline(db, store=store).run(min_chars=10)
    return db, ds, store, {"a": a, "b": b, "c": c, "d": d}


def test_exact_duplicate_relation_and_direction(tmp_path) -> None:
    db, ds, store, ids = _fixture(tmp_path)
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    rels = svc.relations_for(ids["a"], types=[RelationType.EXACT_DUPLICATE.value])
    assert rels and all(r.type == "EXACT_DUPLICATE" and not r.directed for r in rels)
    assert {r.target for r in rels} == {ids["b"]}
    assert rels[0].evidence.get("digest")
    assert svc.relations_for(ids["a"], types=["EXACT_DUPLICATE"])  # self never returned
    assert all(r.source != r.target for r in rels)


def test_version_relation_is_directed(tmp_path) -> None:
    db, ds, store, ids = _fixture(tmp_path)
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    rels = svc.relations_for(ids["c"], types=[RelationType.VERSION_OF.value])
    assert rels and all(r.directed and r.type == "VERSION_OF" for r in rels)
    assert ids["d"] in {r.target for r in rels}


def test_neighborhood_is_bounded_and_no_self_loop(tmp_path) -> None:
    db, ds, store, ids = _fixture(tmp_path)
    g = DocumentGraph(db, intel_store=store, dedup_store=ds)
    nb = g.neighborhood(ids["a"], max_nodes=10, max_edges=10)
    assert len(nb["nodes"]) <= 10 and len(nb["edges"]) <= 10
    for e in nb["edges"]:
        assert e["source"] != e["target"]
        assert e["type"] in {t.value for t in RelationType}
    assert "metrics" in nb and nb["metrics"]["nodes"] >= 1


def test_shared_entity_evidence_is_mention_not_relationship(tmp_path) -> None:
    db, ds, store, ids = _fixture(tmp_path)
    # give two docs a shared organization
    db.update_content(ids["a"], "Contact ACME GmbH for the invoice. " * 10)
    db.update_content(ids["b"], "ACME GmbH sent the contract. " * 10)
    IntelPipeline(db, store=store).run(min_chars=10)
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    rels = svc.relations_for(ids["a"], types=[RelationType.SAME_ENTITY.value])
    for r in rels:
        assert "mention" in r.evidence.get("note", "").lower()
        assert r.type == "SAME_ENTITY"


def test_archive_containment_direction(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    ds = DedupStore(db)
    store = IntelStore(db)
    parent = _add(db, tmp_path / "bundle.zip", "PK")
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (path, filename, size_bytes, modified_at, document_kind, "
            "archive_parent_id, state) VALUES (?,?,?,?,?,?, 'ACTIVE')",
            (str(tmp_path / "bundle.zip!/m.txt"), "m.txt", 3, "2026-01-01",
             "ARCHIVE_MEMBER", parent))
        conn.commit()
        member = conn.execute("SELECT id FROM files WHERE filename='m.txt'").fetchone()["id"]
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    rels = svc.relations_for(int(member), types=[RelationType.ARCHIVE_CONTAINS.value])
    assert any(r.source == parent and r.target == int(member) and r.directed for r in rels)


def test_entity_graph_edges_are_bounded(tmp_path) -> None:
    db, ds, store, ids = _fixture(tmp_path)
    db.update_content(ids["a"], "Contact ACME GmbH info@acme.example " * 10)
    IntelPipeline(db, store=store).run(min_chars=10)
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    g = svc.entity_graph(min_docs=1, max_entities=50, max_edges=50)
    assert g["stats"]["edges"] <= 50
    assert all(e["type"] == "MENTIONS" for e in g["edges"])


def test_networkx_adapter(tmp_path) -> None:
    db, ds, store, ids = _fixture(tmp_path)
    svc = RelationService(db, dedup_store=ds, intel_store=store)
    nb = svc.neighborhood(ids["a"], max_nodes=5, max_edges=5)
    graph = to_networkx(nb)
    assert graph.number_of_nodes() >= 1 and graph.number_of_nodes() <= 5
