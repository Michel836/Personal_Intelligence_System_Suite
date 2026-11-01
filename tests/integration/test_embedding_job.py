"""Resumable embedding job + semantic coverage (Week 3, point 7)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

import src.intelligence.semantic_search as ss
from src.core.coverage import extraction_coverage, semantic_coverage
from src.core.database import DatabaseManager
from src.intelligence.embedding_job import EmbeddingJob, JobState


def _constant(value):
    """Return a zero-argument-compatible factory that always returns *value*."""

    def _factory(*args, **kwargs):  # noqa: ARG001 - signature compatibility
        return value

    return _factory


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.embedding_dim = 4
        self.model_key = "jobkey"
        self.model_name = "job/model"
        self.embedded = 0

    def is_available(self) -> bool:
        return True

    def generate_embedding(self, text: str) -> np.ndarray:
        _ = text
        return np.ones(4, dtype=np.float32)

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        _ = (batch_size, show_progress)
        self.embedded += len(texts)
        return [np.ones(4, dtype=np.float32) for _ in texts]

    def load_embedding_cache(self, key):
        _ = key
        return

    def save_embedding_cache(self, key, embedding):
        _ = (key, embedding)
        return


def _make_db(tmp_path: Path, docs: int = 6) -> DatabaseManager:
    db = DatabaseManager(tmp_path / "job.db")
    with db.get_connection() as conn:
        for i in range(1, docs + 1):
            conn.execute(
                "INSERT INTO files (id, path, filename, extension, size_bytes, "
                "modified_at, state, document_kind, content_extracted) "
                "VALUES (?, ?, ?, '.txt', 200, '2024-01-01', 'ACTIVE', "
                "'PHYSICAL_FILE', 1)",
                (i, f"/corpus/doc{i}.txt", f"doc{i}.txt"),
            )
        conn.commit()
    for i in range(1, docs + 1):
        db.update_content(i, f"Document {i} with enough content to be embedded "
                             "into the semantic store. " * 2)
    return db


def _job(tmp_path: Path, monkeypatch, db: DatabaseManager) -> EmbeddingJob:
    fake = _FakeEmbeddings()
    monkeypatch.setattr(ss, "EmbeddingGenerator", _constant(fake))
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("PIS_EMBEDDING_CACHE_DIR", str(tmp_path / "cache"))
    return EmbeddingJob(db, state_path=tmp_path / "job.json",
                        stop_path=tmp_path / "job.stop",
                        log_path=tmp_path / "job.log")


def test_coverage_reports_embedded_and_pending(tmp_path: Path) -> None:
    db = _make_db(tmp_path, docs=4)
    coverage = semantic_coverage(db)
    assert coverage["eligible"] == 4
    assert coverage["embedded"] == 0
    assert coverage["pending"] == 4
    assert coverage["percent"] == 0.0
    assert extraction_coverage(db)["extracted"] == 4


def test_job_is_bounded_and_resumable(tmp_path: Path, monkeypatch) -> None:
    db = _make_db(tmp_path, docs=6)
    job = _job(tmp_path, monkeypatch, db)

    first = job.run(limit=2, batch_size=2)
    assert first.status == "DONE"
    assert first.embedded == 2
    assert semantic_coverage(db)["embedded"] == 2

    second = job.run(limit=2, batch_size=2)
    assert second.embedded == 2
    assert semantic_coverage(db)["embedded"] == 4

    final = job.run()
    assert final.status == "DONE"
    coverage = semantic_coverage(db)
    assert coverage["embedded"] == 6
    assert coverage["pending"] == 0
    assert coverage["percent"] == 100.0


def test_job_stops_cleanly_and_leaves_work_resumable(tmp_path: Path, monkeypatch) -> None:
    db = _make_db(tmp_path, docs=4)
    job = _job(tmp_path, monkeypatch, db)

    state = job.run(limit=4, batch_size=1, should_stop=lambda: True)
    assert state.status == "STOPPED"
    assert state.embedded == 0
    assert semantic_coverage(db)["embedded"] == 0

    resumed = job.run()
    assert resumed.status == "DONE"
    assert semantic_coverage(db)["embedded"] == 4


def test_stop_request_is_visible_and_a_new_run_clears_it(tmp_path: Path, monkeypatch) -> None:
    db = _make_db(tmp_path, docs=2)
    job = _job(tmp_path, monkeypatch, db)

    job.request_stop()
    assert job.stop_path.exists()
    assert job.status()["stop_requested"] is True

    # A fresh run clears a stale stop request (otherwise every later run would
    # abort immediately) and then completes normally.
    state = job.run()
    assert not job.stop_path.exists()
    assert state.status == "DONE"
    assert semantic_coverage(db)["embedded"] == 2


def test_status_exposes_state_and_coverage(tmp_path: Path, monkeypatch) -> None:
    db = _make_db(tmp_path, docs=3)
    job = _job(tmp_path, monkeypatch, db)
    job.run()
    payload = job.status()
    assert payload["status"] == "DONE"
    assert payload["running"] is False
    assert payload["coverage"]["percent"] == 100.0
    assert isinstance(job.read(), JobState)


def test_unavailable_backend_is_reported_not_crashing(tmp_path: Path, monkeypatch) -> None:
    class _Unavailable(_FakeEmbeddings):
        def is_available(self) -> bool:
            return False

    db = _make_db(tmp_path, docs=1)
    monkeypatch.setattr(ss, "EmbeddingGenerator", _constant(_Unavailable()))
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    job = EmbeddingJob(db, state_path=tmp_path / "job.json",
                       stop_path=tmp_path / "job.stop",
                       log_path=tmp_path / "job.log")
    state = job.run()
    assert state.status == "NOT_CONFIGURED"
    assert "ai" in (state.error or "")
