"""Semantic freshness: changed content re-embeds, MISSING docs cannot surface.

Regression for the M009I review concern that deleted/changed documents could
leave stale vectors and crowd semantic top-k. M011 drives changes through the
canonical write paths so the incremental dirty-state refresh is exercised.
"""
from __future__ import annotations

import numpy as np

import src.intelligence.semantic_search as ss
from src.core.database import DatabaseManager


class _FakeEmbeddings:
    KEYWORDS = ["alpha", "beta", "gamma", "delta"]

    def __init__(self) -> None:
        self.embedding_dim = len(self.KEYWORDS)
        self.model_key = "fake"
        self.model_name = "fake/model"

    def is_available(self) -> bool:
        return True

    def _vec(self, text: str) -> np.ndarray:
        vec = np.zeros(self.embedding_dim, dtype=np.float32)
        for i, kw in enumerate(self.KEYWORDS):
            if kw in text.lower():
                vec[i] = 1.0
        return vec if vec.any() else np.full(self.embedding_dim, 0.25, dtype=np.float32)

    def generate_embedding(self, text: str):
        return self._vec(text)

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        return [self._vec(t) for t in texts]

    def load_embedding_cache(self, key):
        return None

    def save_embedding_cache(self, key, embedding):
        return None


def _seed(db: DatabaseManager, rows):
    with db.get_connection() as conn:
        for row_id, state, _text in rows:
            conn.execute(
                "INSERT INTO files (id, path, filename, size_bytes, modified_at, "
                "state, document_kind) VALUES (?, ?, ?, 10, '2026-01-01', ?, 'PHYSICAL_FILE')",
                (row_id, f"/corpus/doc{row_id}.txt", f"doc{row_id}.txt", state),
            )
        conn.commit()
    for row_id, _state, text in rows:
        db.update_content(row_id, text)


def _engine(tmp_path, monkeypatch, name):
    monkeypatch.setattr(ss, "EmbeddingGenerator", _FakeEmbeddings)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / name))
    db = DatabaseManager(tmp_path / f"{name}.db")
    return db, ss.SemanticSearchEngine(db)


def test_changed_content_is_reembedded(tmp_path, monkeypatch) -> None:
    db, engine = _engine(tmp_path, monkeypatch, "changed")
    _seed(db, [
        (1, "ACTIVE", "beta gamma delta filler filler filler filler filler"),
        (2, "ACTIVE", "delta delta delta filler filler filler filler filler"),
    ])
    first = engine.semantic_search("alpha", limit=2, similarity_threshold=0.5)
    assert not first

    # Content changes through the canonical writer -> must refresh, not reuse.
    db.update_content(1, "alpha alpha alpha " + "filler " * 10)
    results = engine.semantic_search("alpha", limit=2, similarity_threshold=0.5)
    assert results and results[0]["id"] == 1


def test_missing_doc_is_pruned_and_not_returned(tmp_path, monkeypatch) -> None:
    db, engine = _engine(tmp_path, monkeypatch, "missing")
    _seed(db, [
        (1, "ACTIVE", "alpha alpha alpha " + "filler " * 10),
        (2, "ACTIVE", "beta beta beta " + "filler " * 10),
    ])
    before = engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)
    assert any(d["id"] == 1 for d in before)

    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=1")
        conn.commit()
    db.mark_semantic_sweep_due()  # as a completed scan would
    after = engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)
    assert all(d["id"] != 1 for d in after), "MISSING document must never be returned"

    store = engine._get_store()
    assert store.load()
    assert 1 not in set(store.meta.ids), "MISSING id must be pruned from the store"
