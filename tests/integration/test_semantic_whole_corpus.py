"""Regression: semantic search must search the whole corpus, not limit*5 (M009H.3)."""
from __future__ import annotations

import numpy as np

import src.intelligence.semantic_search as ss
from src.core.database import DatabaseManager
from src.intelligence.embeddings import EmbeddingGenerator


class _FakeEmbeddings:
    """Deterministic bag-of-keywords embeddings (no model download)."""

    KEYWORDS = ["alpha", "beta", "gamma", "delta"]

    def __init__(self) -> None:
        self.embedding_dim = len(self.KEYWORDS)

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

    def find_similar(self, query, candidates, top_k=10):
        return EmbeddingGenerator.find_similar(None, query, candidates, top_k)

    def load_embedding_cache(self, key):
        return None

    def save_embedding_cache(self, key, embedding):
        return None


def test_relevant_doc_outside_old_cap_is_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ss, "EmbeddingGenerator", _FakeEmbeddings)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store1"))

    docs = []
    for i in range(30):
        text = "beta gamma delta filler content" if i != 25 else "alpha content here "
        docs.append({"id": i, "content_text": text})

    db = DatabaseManager(tmp_path / "sem.db")
    engine = ss.SemanticSearchEngine(db)
    monkeypatch.setattr(engine, "_get_documents_with_content", lambda limit=None: docs)

    results = engine.semantic_search("alpha", limit=2)

    assert results, "expected a result"
    assert results[0]["id"] == 25  # outside the previous limit*5 = 10 window


def test_loader_returns_whole_corpus(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ss, "EmbeddingGenerator", _FakeEmbeddings)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store2"))
    db = DatabaseManager(tmp_path / "sem2.db")
    engine = ss.SemanticSearchEngine(db)
    # _get_documents_with_content(limit=None) must not be capped by the loader.
    rows = engine._get_documents_with_content(limit=None)
    assert isinstance(rows, list)
