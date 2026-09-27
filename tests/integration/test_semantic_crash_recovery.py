"""M011: semantic refresh is restart/crash safe (at-least-once, idempotent)."""
from __future__ import annotations

import numpy as np
import pytest

import src.intelligence.semantic_search as ss
from src.core.database import DatabaseManager


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.model_key = "crash"
        self.model_name = "crash/model"
        self.embedding_dim = 4

    def is_available(self):
        return True

    def _vec(self, text):
        v = np.zeros(4, dtype=np.float32)
        v[len(text) % 4] = 1.0
        return v

    def generate_embedding(self, text):
        return self._vec(text)

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        return [self._vec(t) for t in texts]


def _engine(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "EmbeddingGenerator", _FakeEmbeddings)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    db = DatabaseManager(tmp_path / "crash.db")
    with db.get_connection() as conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO files (id, path, filename, size_bytes, modified_at, "
                "state, document_kind) VALUES (?, ?, ?, 10, '2026-01-01', 'ACTIVE', 'PHYSICAL_FILE')",
                (i, f"/c/d{i}.txt", f"d{i}.txt"),
            )
        conn.commit()
    for i in range(5):
        db.update_content(i, f"document {i} content " * 5)
    return db, ss.SemanticSearchEngine(db)


def _dirty_ids(db):
    with db.get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT file_id FROM semantic_state WHERE dirty=1")]


def test_store_write_failure_leaves_rows_dirty(tmp_path, monkeypatch) -> None:
    db, engine = _engine(tmp_path, monkeypatch)
    store = engine._get_store()
    original = store.append

    def boom(*a, **k):
        raise RuntimeError("simulated disk failure")

    monkeypatch.setattr(store, "append", boom)
    with pytest.raises(RuntimeError):
        engine.semantic_search("document", limit=3, similarity_threshold=0.0)
    assert _dirty_ids(db), "rows must remain pending after a failed store write"

    monkeypatch.setattr(store, "append", original)
    engine.semantic_search("document", limit=3, similarity_threshold=0.0)
    assert _dirty_ids(db) == []
    store.load()
    assert len(set(store.meta.ids)) == 5


def test_clean_mark_failure_converges_on_retry(tmp_path, monkeypatch) -> None:
    db, engine = _engine(tmp_path, monkeypatch)
    original = db.mark_semantic_embedded
    calls = {"n": 0}

    def flaky(entries, *, model_key, dim):
        calls["n"] += 1
        if calls["n"] == 1:
            return  # simulate crash before the clean-mark committed
        return original(entries, model_key=model_key, dim=dim)

    monkeypatch.setattr(db, "mark_semantic_embedded", flaky)
    engine.semantic_search("document", limit=3, similarity_threshold=0.0)
    assert _dirty_ids(db), "clean mark was skipped -> rows must stay dirty"

    engine.semantic_search("document", limit=3, similarity_threshold=0.0)
    assert _dirty_ids(db) == []
    store = engine._get_store()
    store.load()
    assert len(set(store.meta.ids)) == 5  # idempotent replace, no duplicates


def test_interrupted_prune_is_idempotent(tmp_path, monkeypatch) -> None:
    db, engine = _engine(tmp_path, monkeypatch)
    engine.semantic_search("document", limit=5, similarity_threshold=0.0)

    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=0")
        conn.commit()
    db.mark_semantic_sweep_due()

    original = db.mark_semantic_pruned
    calls = {"n": 0}

    def flaky(ids):
        calls["n"] += 1
        if calls["n"] == 1:
            return  # crash before persisting the prune outcome
        return original(ids)

    monkeypatch.setattr(db, "mark_semantic_pruned", flaky)
    engine.semantic_search("document", limit=5, similarity_threshold=0.0)
    # Prune persists on the retry and the row disappears for good.
    engine.semantic_search("document", limit=5, similarity_threshold=0.0)
    store = engine._get_store()
    store.load()
    assert 0 not in set(store.meta.ids)
