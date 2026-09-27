"""Near-duplicate + version-family tests (M014)."""
from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from src.core.database import DatabaseManager
from src.dedup import DedupStore, NearDuplicateEngine, VersionTracker
from src.intelligence.embedding_store import EmbeddingMatrixStore
from src.scanner.models import FileType

_T0 = datetime.datetime(2026, 1, 1, 12, 0, 0)


def _save(db, factory, path: Path, *, mtime=_T0):
    return db.save_file(factory(path, size_bytes=path.stat().st_size,
                                file_type=FileType.DOCUMENT, modified_at=mtime))


def _id_of(db, path: Path) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM files WHERE path=?", (str(path),)).fetchone()[0])


def _seed_content(db, fid: int, text: str) -> None:
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET content_text=?, content_extracted=1 WHERE id=?", (text, fid))
        conn.commit()


def test_near_duplicate_excludes_exact_and_respects_threshold(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    dstore = DedupStore(db)
    base = "alpha beta gamma delta epsilon zeta eta theta iota kappa " * 30
    near = base + " lambda mu nu"
    unrelated = "quantum compiler optimizer runtime kernel scheduler " * 30

    ids = {}
    for name, text in (("base.txt", base), ("near.txt", near),
                       ("exact_copy.txt", base), ("unrelated.txt", unrelated)):
        p = tmp_path / name
        p.write_text(text)
        fid = _save(db, file_info_factory, p)
        _seed_content(db, fid, text)
        ids[name] = fid

    estore = EmbeddingMatrixStore("m", "m", 8, base_dir=tmp_path / "store")
    ordered = [ids["base.txt"], ids["near.txt"], ids["exact_copy.txt"], ids["unrelated.txt"]]
    vecs = np.asarray([
        [1, 0, 0, 0, 0, 0, 0, 0],
        [0.99, 0.1, 0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 1, 0, 0, 0],
    ], dtype=np.float32)
    estore.save(ordered, vecs, hashes=[
        "h_base", "h_near", "h_base", "h_unrelated",
    ])
    estore.load()

    engine = NearDuplicateEngine(db, dstore, embed_store=estore)
    res = engine.build(threshold=0.9, min_chars=50)
    assert res["near_duplicate_edges"] >= 1

    others = {e["other_id"] for e in dstore.near_duplicates_for(ids["base.txt"], limit=10)}
    assert ids["near.txt"] in others
    assert ids["exact_copy.txt"] not in others  # exact duplicates are excluded

    # A very high threshold removes the near edge.
    res2 = engine.build(threshold=0.999)
    assert res2["near_duplicate_edges"] == 0


def test_version_family_confidence_and_order(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    dstore = DedupStore(db)
    d = tmp_path / "docs"
    d.mkdir()
    for name, mtime in (("rapport_v1.txt", datetime.datetime(2026, 1, 1)),
                        ("rapport_v2.txt", datetime.datetime(2026, 2, 1)),
                        ("rapport_final.txt", datetime.datetime(2026, 3, 1))):
        p = d / name
        p.write_text("content of " + name + " " * 20)
        _save(db, file_info_factory, p, mtime=mtime)
    for name in ("unrelated_notes.txt", "budget.txt", "budget (1).txt"):
        p = d / name
        p.write_text(name + " " * 20)
        _save(db, file_info_factory, p)

    tracker = VersionTracker(db, dstore)
    res = tracker.build()
    assert res["by_confidence"].get("HIGH", 0) >= 1

    fam = tracker.family_for_file(_id_of(db, d / "rapport_v2.txt"))
    assert fam is not None
    assert [m["filename"] for m in fam["members"]] == [
        "rapport_v1.txt", "rapport_v2.txt", "rapport_final.txt"]
    assert fam["confidence"] == "HIGH"

    # budget family has only one explicit marker -> must not be claimed HIGH.
    budget_fam = tracker.family_for_file(_id_of(db, d / "budget.txt"))
    assert budget_fam is not None
    assert budget_fam["confidence"] in {"MEDIUM", "UNORDERED"}
    # Unrelated single file is not part of any family.
    assert tracker.family_for_file(_id_of(db, d / "unrelated_notes.txt")) is None
