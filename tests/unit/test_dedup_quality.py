"""M014 labelled quality benchmark (precision-oriented, deterministic)."""
from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from src.core.database import DatabaseManager
from src.dedup import DedupStore, NearDuplicateEngine, VersionTracker
from src.dedup.exact import ExactDuplicateEngine
from src.dedup.hashing import ContentHasher
from src.dedup.rerank import fuse_results
from src.intelligence.embedding_store import EmbeddingMatrixStore
from src.scanner.models import FileType


def _save(db, factory, path: Path, mtime=datetime.datetime(2026, 1, 1)):
    return db.save_file(factory(path, size_bytes=path.stat().st_size,
                                file_type=FileType.DOCUMENT, modified_at=mtime))


def _seed(db, fid, text):
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET content_text=?, content_extracted=1 WHERE id=?", (text, fid))
        conn.commit()


def test_exact_precision_and_recall(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    exact = ExactDuplicateEngine(db, store, ContentHasher(db, store))
    docs = {
        "e1a.txt": "exact duplicate body " * 30,
        "e1b.txt": "exact duplicate body " * 30,          # exact positive
        "e2a.bin": "A" * 500, "e2b.bin": "A" * 499 + "B",  # same size, different (negative)
        "unique.txt": "totally unique length here",
    }
    for name, text in docs.items():
        p = tmp_path / name
        p.write_text(text)
        _save(db, file_info_factory, p)
    exact.hash_duplicate_candidates(min_size=1)
    groups = exact.groups(min_size=1)
    members = {m["filename"] for g in groups for m in g["members"]}
    assert {"e1a.txt", "e1b.txt"} <= members       # positive found
    assert "e2a.bin" not in members and "e2b.bin" not in members  # negative rejected
    assert all(g["count"] > 1 for g in groups)     # no singleton groups


def test_near_precision_and_recall(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    base = "alpha beta gamma delta epsilon zeta eta theta " * 40
    near = base + " lambda mu"
    other = "quantum kernel scheduler compiler optimizer " * 40
    ids = {}
    for name, text in (("base.txt", base), ("near.txt", near), ("exact.txt", base), ("other.txt", other)):
        p = tmp_path / name
        p.write_text(text)
        fid = _save(db, file_info_factory, p)
        _seed(db, fid, text)
        ids[name] = fid
    estore = EmbeddingMatrixStore("m", "m", 8, base_dir=tmp_path / "st")
    ordered = [ids["base.txt"], ids["near.txt"], ids["exact.txt"], ids["other.txt"]]
    estore.save(ordered, np.asarray([[1, 0, 0, 0, 0, 0, 0, 0],
                                     [0.98, 0.1, 0, 0, 0, 0, 0, 0],
                                     [1, 0, 0, 0, 0, 0, 0, 0],
                                     [0, 0, 0, 0, 1, 0, 0, 0]], dtype=np.float32),
                hashes=["h", "h_near", "h", "h_other"])
    estore.load()
    engine = NearDuplicateEngine(db, store, embed_store=estore)
    engine.build(threshold=0.9, min_chars=50)
    others = {e["other_id"] for e in store.near_duplicates_for(ids["base.txt"], limit=10)}
    assert ids["near.txt"] in others           # near positive found
    assert ids["exact.txt"] not in others      # exact duplicate not reported as near
    assert ids["other.txt"] not in others      # unrelated rejected


def test_version_precision_and_no_invented_order(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = DedupStore(db)
    d = tmp_path / "d"
    d.mkdir()
    for name in ("note_v1.txt", "note_v2.txt"):
        p = d / name
        p.write_text(name + " body " * 20)
        _save(db, file_info_factory, p)
    for name in ("alpha.txt", "beta.txt"):
        p = d / name
        p.write_text(name + " body " * 20)
        _save(db, file_info_factory, p)
    tracker = VersionTracker(db, store)
    tracker.build()
    fam = tracker.family_for_file(_id(db, d / "note_v2.txt"))
    assert fam is not None and fam["confidence"] == "HIGH"
    assert tracker.family_for_file(_id(db, d / "alpha.txt")) is None  # unrelated negative


def test_rerank_preserves_exact_lexical() -> None:
    lexical = [{"id": 1, "filename": "budget_report.txt"}, {"id": 2, "filename": "x.txt"}]
    semantic = [{"id": 3, "filename": "y.txt"}, {"id": 4, "filename": "z.txt"}]
    out = fuse_results(lexical, semantic, query="budget_report", limit=5)
    assert out[0]["id"] == 1


def _id(db, path: Path) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM files WHERE path=?", (str(path),)).fetchone()[0])
