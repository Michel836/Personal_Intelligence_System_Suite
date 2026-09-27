"""Duplicate-aware reranking / fusion tests (M014)."""
from __future__ import annotations

import datetime
from pathlib import Path

from src.core.database import DatabaseManager
from src.dedup import DedupStore, fuse_results
from src.dedup.rerank import rerank_search
from src.scanner.models import FileType


def _save(db, factory, path: Path, *, mtime=datetime.datetime(2026, 1, 1)):
    return db.save_file(factory(path, size_bytes=10, file_type=FileType.DOCUMENT, modified_at=mtime))


class _FakeSemantic:
    def __init__(self, results):
        self._results = results

    def is_available(self):
        return True

    def semantic_search(self, query, limit=20, similarity_threshold=0.0):
        return self._results[:limit]


def test_exact_title_hit_survives_fusion() -> None:
    lexical = [{"id": 1, "filename": "zeta.txt", "path": "/z/zeta.txt"},
               {"id": 2, "filename": "report.txt", "path": "/r/report.txt"}]
    semantic = [{"id": 3, "filename": "other.txt", "path": "/o/other.txt"},
                {"id": 1, "filename": "zeta.txt", "path": "/z/zeta.txt"}]
    out = fuse_results(lexical, semantic, query="report", limit=5)
    assert out[0]["id"] == 2  # exact filename match is boosted above both lists
    assert any(d["id"] == 2 and d.get("exact_title_boost") for d in out)


def test_lexical_fallback_preserves_order() -> None:
    lexical = [{"id": i, "filename": f"f{i}.txt", "path": f"/x/f{i}.txt"} for i in range(1, 6)]
    out = fuse_results(lexical, [], query="nothing", limit=5)
    assert [d["id"] for d in out] == [1, 2, 3, 4, 5]


def test_duplicate_collapse_and_version_diversity(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    dstore = DedupStore(db)
    a = _save(db, file_info_factory, tmp_path / "a.txt")
    b = _save(db, file_info_factory, tmp_path / "b_copy.txt")
    c = _save(db, file_info_factory, tmp_path / "c.txt")
    # a and b are exact duplicates; a and c are versions.
    dstore.set_hash(a, digest="feed", size_bytes=10, modified_at=None)
    dstore.set_hash(b, digest="feed", size_bytes=10, modified_at=None)
    dstore.set_hash(c, digest="cafe", size_bytes=10, modified_at=None)
    dstore.replace_version_families([{
        "family_key": "version:x", "base_name": "x", "directory": "/",
        "confidence": "MEDIUM", "evidence": {},
        "members": [{"id": a, "rank": 0}, {"id": c, "rank": 1, "is_primary": 1}],
    }])
    lexical = [{"id": a, "filename": "a.txt"}, {"id": b, "filename": "b_copy.txt"},
               {"id": c, "filename": "c.txt"}]

    collapsed = fuse_results(lexical, [], query="", limit=10, dedup_store=dstore)
    ids = [d["id"] for d in collapsed]
    assert a in ids and b not in ids and c in ids  # one exact copy kept

    diverse = fuse_results(lexical, [], query="", limit=10, dedup_store=dstore,
                           collapse_duplicates=False, version_diversity=True)
    div_ids = [d["id"] for d in diverse]
    assert a in div_ids and c not in div_ids  # one member per version family kept

    all_copies = fuse_results(lexical, [], query="", limit=10, dedup_store=dstore,
                              collapse_duplicates=True, version_diversity=True,
                              show_all_copies=True, show_all_versions=True)
    assert {a, b, c} <= {d["id"] for d in all_copies}


def test_rerank_search_lexical_fallback(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    p = tmp_path / "report.txt"
    p.write_text("report body")
    _save(db, file_info_factory, p)
    out = rerank_search(db, None, "report", limit=5)
    assert isinstance(out, list)
