"""Fallback / failure-isolation tests for the semantic stack (M009I.12, M011)."""
from __future__ import annotations

import numpy as np

import src.intelligence.semantic_search as ss
from src.core.database import DatabaseManager
from src.intelligence.embedding_store import EmbeddingMatrixStore
from src.intelligence.embeddings import EmbeddingGenerator


class _FakeEmbeddings:
    def __init__(self, key="fake", dim=6):
        self.model_key = key
        self.model_name = key
        self.embedding_dim = dim

    def is_available(self):
        return True

    def _vec(self, text):
        v = np.zeros(self.embedding_dim, dtype=np.float32)
        for i, ch in enumerate(text[: self.embedding_dim]):
            v[i] = float(ord(ch) % 7)
        return v if v.any() else np.ones(self.embedding_dim, dtype=np.float32)

    def generate_embedding(self, text):
        return self._vec(text)

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        return [self._vec(t) for t in texts]

    def load_embedding_cache(self, key):
        return None

    def save_embedding_cache(self, key, embedding):
        return None


def _seed(db: DatabaseManager, count: int = 10) -> None:
    with db.get_connection() as conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO files (id, path, filename, size_bytes, modified_at, "
                "state, document_kind) VALUES (?, ?, ?, 10, '2026-01-01', 'ACTIVE', 'PHYSICAL_FILE')",
                (i, f"/corpus/doc{i}.txt", f"doc{i}.txt"),
            )
        conn.commit()
    for i in range(count):
        db.update_content(i, f"document number {i} content about topic {i} " * 3)


def test_corrupt_store_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "EmbeddingGenerator", _FakeEmbeddings)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    db = DatabaseManager(tmp_path / "db.db")
    _seed(db)
    engine = ss.SemanticSearchEngine(db)

    assert engine.semantic_search("document", limit=3)
    # Corrupt the persisted meta and force a reload; a rebuild must still work.
    store = engine._get_store()
    (store.dir / "meta.json").write_text("{not json")
    engine._store = None
    assert engine.semantic_search("document", limit=3)


def test_model_switch_uses_new_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    db = DatabaseManager(tmp_path / "db.db")
    _seed(db)
    engine = ss.SemanticSearchEngine(db)

    engine.embedding_gen = _FakeEmbeddings("modelA", 6)
    engine._store = None
    assert engine.semantic_search("document", limit=3)
    first_dir = engine._get_store().dir

    engine.embedding_gen = _FakeEmbeddings("modelB", 6)
    engine._store = None
    assert engine.semantic_search("document", limit=3)
    assert engine._get_store().dir != first_dir


def test_dimension_mismatch_store_search_raises(tmp_path):
    store = EmbeddingMatrixStore("m", "m", 8, base_dir=tmp_path)
    store.save([1, 2], np.ones((2, 8), dtype=np.float32))
    try:
        store.search(np.ones(4, dtype=np.float32), 1)
        raise AssertionError("expected dimension mismatch")
    except Exception as exc:
        assert "dim" in str(exc).lower() or "mismatch" in str(exc).lower()
