"""M011: incremental semantic change-tracking, generation cache, boundedness."""
from __future__ import annotations

import numpy as np

import src.intelligence.semantic_search as ss
from src.core.database import DatabaseManager


class _CountingEmbeddings:
    """Deterministic embeddings that count how many texts were embedded."""

    KEYWORDS = ["alpha", "beta", "gamma", "delta"]

    def __init__(self) -> None:
        self.embedding_dim = len(self.KEYWORDS)
        self.model_key = "counting"
        self.model_name = "counting/model"
        self.embedded = 0

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
        self.embedded += len(texts)
        return [self._vec(t) for t in texts]

    def load_embedding_cache(self, key):
        return None

    def save_embedding_cache(self, key, embedding):
        return None


def _engine(tmp_path, monkeypatch, name):
    fake = _CountingEmbeddings()
    monkeypatch.setattr(ss, "EmbeddingGenerator", lambda *a, **k: fake)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / name))
    monkeypatch.setenv("PIS_EMBEDDING_CACHE_DIR", str(tmp_path / f"{name}-cache"))
    db = DatabaseManager(tmp_path / f"{name}.db")
    return db, ss.SemanticSearchEngine(db), fake


def _insert(db: DatabaseManager, ids, text_prefix="beta gamma "):
    with db.get_connection() as conn:
        for i in ids:
            conn.execute(
                "INSERT INTO files (id, path, filename, size_bytes, modified_at, "
                "state, document_kind) VALUES (?, ?, ?, 10, '2026-01-01', 'ACTIVE', 'PHYSICAL_FILE')",
                (i, f"/corpus/doc{i}.txt", f"doc{i}.txt"),
            )
        conn.commit()
    for i in ids:
        db.update_content(i, f"{text_prefix}filler " * 12)


def _state(db: DatabaseManager, file_id: int):
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT dirty, prune, content_version, embedded_version, model_key, dim "
            "FROM semantic_state WHERE file_id = ?", (file_id,)).fetchone()
        return dict(row) if row else None


def test_new_content_is_dirty_then_embed_then_clean(tmp_path, monkeypatch) -> None:
    db, engine, fake = _engine(tmp_path, monkeypatch, "clean")
    _insert(db, [1, 2])
    assert _state(db, 1)["dirty"] == 1

    engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    s = _state(db, 1)
    assert s["dirty"] == 0 and s["prune"] == 0
    assert s["content_version"] == s["embedded_version"]
    assert s["model_key"] == "counting" and s["dim"] == 4


def test_metadata_only_change_does_not_reembed(tmp_path, monkeypatch) -> None:
    db, engine, fake = _engine(tmp_path, monkeypatch, "meta")
    _insert(db, [1, 2, 3])
    engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    baseline = fake.embedded

    # Path-only change (rename) with identical content must not re-embed.
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET path='/corpus/renamed1.txt', filename='renamed1.txt' WHERE id=1")
        conn.commit()
    engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    assert fake.embedded == baseline


def test_refresh_embeds_only_changed_rows(tmp_path, monkeypatch) -> None:
    db, engine, fake = _engine(tmp_path, monkeypatch, "bounded")
    _insert(db, list(range(50)))
    engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    assert fake.embedded == 50

    for i in (3, 7, 11):
        db.update_content(i, "alpha changed content " * 4)
    engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    assert fake.embedded == 53  # exactly the 3 changed rows


def test_same_session_query_cache_invalidated_after_change(tmp_path, monkeypatch) -> None:
    db, engine, fake = _engine(tmp_path, monkeypatch, "cache")
    _insert(db, [1, 2])
    first = engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)
    assert not first  # cached empty result

    db.update_content(1, "alpha alpha alpha " * 5)
    # Same engine instance, same query: the result must be fresh.
    second = engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)
    assert second and second[0]["id"] == 1


def test_missing_is_pruned_on_next_query(tmp_path, monkeypatch) -> None:
    db, engine, fake = _engine(tmp_path, monkeypatch, "prune")
    _insert(db, [1, 2], text_prefix="alpha ")
    assert engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=1")
        conn.commit()
    db.mark_semantic_sweep_due()  # as a completed scan would
    results = engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)
    assert all(d["id"] != 1 for d in results)
    store = engine._get_store()
    store.load()
    assert 1 not in set(store.meta.ids)


def test_legacy_content_is_swept_once(tmp_path, monkeypatch) -> None:
    db, engine, fake = _engine(tmp_path, monkeypatch, "legacy")
    # Raw insert simulates a pre-M011 DB (no semantic_state row).
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, size_bytes, modified_at, content_text, "
            "content_extracted, state, document_kind) VALUES (1, '/c/d.txt', 'd.txt', 10, "
            "'2026-01-01', ?, 1, 'ACTIVE', 'PHYSICAL_FILE')",
            ("beta gamma content " * 10,),
        )
        conn.commit()
    assert engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    assert _state(db, 1)["embedded_version"] is not None


def test_scan_lifecycle_missing_is_reconciled(tmp_path, monkeypatch) -> None:
    from src.core.scan_service import ScanRequest, ScanService
    from src.core.volume import VolumeInfo

    monkeypatch.setattr(ss, "EmbeddingGenerator", lambda *a, **k: _CountingEmbeddings())
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "scanstore"))
    root = tmp_path / "corpus"
    root.mkdir()
    doc = root / "a.txt"
    doc.write_text("alpha alpha alpha " + "filler " * 10, encoding="utf-8")
    db = DatabaseManager(tmp_path / "scan.db")
    vol = VolumeInfo(stable_key="S", device="S", mountpoint=str(tmp_path), is_available=True)
    ScanService(db).run(ScanRequest(root=root, batch_size=10, volume=vol))
    fid = db.search_files(limit=10)[0]["id"]
    db.update_content(fid, "alpha alpha alpha " + "filler " * 10)
    engine = ss.SemanticSearchEngine(db)
    assert engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)

    doc.unlink()
    ScanService(db).run(ScanRequest(root=root, batch_size=10, volume=vol))
    results = engine.semantic_search("alpha", limit=5, similarity_threshold=0.5)
    assert all(d["id"] != fid for d in results), "deleted file must be pruned after a scan"


def test_store_loss_forces_full_rebuild(tmp_path, monkeypatch) -> None:
    db, engine, fake = _engine(tmp_path, monkeypatch, "loss")
    _insert(db, [1, 2])
    engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    store = engine._get_store()
    for path in (store._matrix_path, store._ids_path, store._hashes_path, store._meta_path):
        path.unlink()
    engine._store = None
    before = fake.embedded

    results = engine.semantic_search("beta", limit=5, similarity_threshold=0.0)
    assert results, "a lost/corrupt store must be rebuilt, not silently empty"
    assert fake.embedded > before
