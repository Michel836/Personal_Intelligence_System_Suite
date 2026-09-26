"""Fallback / failure-isolation tests for the semantic stack (M009I.12)."""
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

    def find_similar(self, q, c, top_k=10):
        return EmbeddingGenerator.find_similar(None, q, c, top_k)


def _docs():
    return [{"id": i, "content_text": f"document number {i} content about topic {i}"} for i in range(10)]


def test_corrupt_store_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "EmbeddingGenerator", _FakeEmbeddings)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    db = DatabaseManager(tmp_path / "db.db")
    engine = ss.SemanticSearchEngine(db)
    monkeypatch.setattr(engine, "_get_documents_with_content", lambda limit=None: _docs())

    assert engine.semantic_search("document", limit=3)
    # Corrupt the persisted meta and ensure a rebuild still yields results.
    store = engine._get_store()
    (store.dir / "meta.json").write_text("{not json")
    assert engine.semantic_search("document", limit=3)


def test_model_switch_uses_new_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    db = DatabaseManager(tmp_path / "db.db")
    engine = ss.SemanticSearchEngine(db)
    monkeypatch.setattr(engine, "_get_documents_with_content", lambda limit=None: _docs())

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


def test_embedding_unavailable_falls_back_to_fts(tmp_path, monkeypatch):
    import src.mcp_server as mcp

    db = DatabaseManager(tmp_path / "db.db")
    from src.core.scan_service import ScanRequest, ScanService
    from src.core.volume import VolumeInfo

    root = tmp_path / "c"
    root.mkdir()
    (root / "rapport.txt").write_text("contenu", encoding="utf-8")
    monkeypatch.setenv("PIS_DB_PATH", str(db.db_path))
    ScanService(db).run(ScanRequest(root=root, volume=VolumeInfo(stable_key="V", device="V", mountpoint=str(tmp_path), is_available=True)))
    monkeypatch.setattr(ss.SemanticSearchEngine, "is_available", lambda self: False)
    rows = mcp.semantic_search("rapport", limit=3)
    assert rows and all("embedding_model" in r for r in rows)
