"""M011: concurrent semantic queries and concurrent extraction/refresh safety."""
from __future__ import annotations

import threading
import time

import numpy as np

import src.intelligence.semantic_search as ss
from src.core.database import DatabaseManager


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.model_key = "conc"
        self.model_name = "conc/model"
        self.embedding_dim = 8
        self._lock = threading.Lock()
        self.embedded = 0

    def is_available(self):
        return True

    def _vec(self, text):
        v = np.zeros(8, dtype=np.float32)
        v[len(text) % 8] = 1.0
        v[(len(text) // 8) % 8] = 0.5
        return v

    def generate_embedding(self, text):
        return self._vec(text)

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        with self._lock:
            self.embedded += len(texts)
        return [self._vec(t) for t in texts]


def _engine(tmp_path, monkeypatch, name, n=200):
    fake = _FakeEmbeddings()
    monkeypatch.setattr(ss, "EmbeddingGenerator", lambda *a, **k: fake)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / name))
    db = DatabaseManager(tmp_path / f"{name}.db")
    with db.get_connection() as conn:
        conn.executemany(
            "INSERT INTO files (id, path, filename, size_bytes, modified_at, state, document_kind) "
            "VALUES (?, ?, ?, 10, '2026-01-01', 'ACTIVE', 'PHYSICAL_FILE')",
            [(i, f"/c/d{i}.txt", f"d{i}.txt") for i in range(n)],
        )
        conn.commit()
    for i in range(n):
        db.update_content(i, f"document {i} " + "beta gamma content " * 5)
    return db, ss.SemanticSearchEngine(db)


def test_concurrent_queries_and_updates_no_corruption(tmp_path, monkeypatch) -> None:
    db, engine = _engine(tmp_path, monkeypatch, "conc")
    errors = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                engine.semantic_search("beta", limit=10, similarity_threshold=0.0)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"reader: {exc!r}")

    def writer():
        for i in range(80):
            try:
                db.update_content(i, "alpha changed content " * 4)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"writer: {exc!r}")
            time.sleep(0.001)

    readers = [threading.Thread(target=reader) for _ in range(3)]
    writer_thread = threading.Thread(target=writer)
    for t in readers:
        t.start()
    writer_thread.start()
    writer_thread.join(timeout=60)
    stop.set()
    for t in readers:
        t.join(timeout=10)

    assert not errors, errors
    # Store remains consistent and queryable.
    store = engine._get_store()
    assert store.load()
    assert len(set(store.meta.ids)) == store.meta.count
    results = engine.semantic_search("beta", limit=10, similarity_threshold=0.0)
    assert results
