"""M011: persistent semantic paths honour explicit env overrides."""
from __future__ import annotations

import numpy as np

import src.intelligence.embeddings as em
import src.intelligence.semantic_search as ss
from src.core.database import DatabaseManager


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.model_key = "pathkey"
        self.model_name = "path/model"
        self.embedding_dim = 4

    def is_available(self):
        return True

    def generate_embedding(self, text):
        return np.ones(4, dtype=np.float32)

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        return [np.ones(4, dtype=np.float32) for _ in texts]


def test_embedding_cache_dir_honors_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(em, "SENTENCE_TRANSFORMERS_AVAILABLE", False)
    monkeypatch.setenv("PIS_EMBEDDING_CACHE_DIR", str(tmp_path / "cache"))
    gen = em.EmbeddingGenerator("bge-m3")
    assert gen.cache_dir == tmp_path / "cache" / "bge-m3"
    assert gen.cache_dir.exists()


def test_embedding_cache_default_stays_under_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(em, "SENTENCE_TRANSFORMERS_AVAILABLE", False)
    monkeypatch.delenv("PIS_EMBEDDING_CACHE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    gen = em.EmbeddingGenerator("bge-m3")
    assert gen.cache_dir == __import__("pathlib").Path("data/cache/embeddings/bge-m3")
    assert (tmp_path / "data" / "cache" / "embeddings" / "bge-m3").exists()


def test_store_dir_is_isolated(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ss, "EmbeddingGenerator", _FakeEmbeddings)
    store_dir = tmp_path / "store"
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(store_dir))
    db = DatabaseManager(tmp_path / "iso.db")
    engine = ss.SemanticSearchEngine(db)
    store = engine._get_store()
    assert store.dir == store_dir / "pathkey"
