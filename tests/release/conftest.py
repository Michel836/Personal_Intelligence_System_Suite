"""Shared fixtures for the release acceptance suite (M021)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from .corpus import AcceptanceCorpus, build_acceptance_corpus
from .fakes import HashingEmbeddingGenerator


@dataclass
class ReleaseEnv:
    root: Path
    corpus: AcceptanceCorpus
    db: Any
    generator: HashingEmbeddingGenerator
    store_dir: Path
    engine: Any

    def file_id(self, relpath: str) -> int:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT id FROM files WHERE path=?",
                               (str(self.corpus.path(relpath)),)).fetchone()
        assert row is not None, f"missing indexed fixture: {relpath}"
        return int(row[0])


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "release.db"))
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("PIS_EMBEDDING_CACHE_DIR", str(tmp_path / "embcache"))
    monkeypatch.setenv("PIS_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("PIS_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("PIS_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("PIS_OCR_ENABLED", "0")
    monkeypatch.setenv("PIS_REMOTE_CONTENT_POLICY", "never")
    monkeypatch.setenv("PIS_LAUNCH_PROFILE", "full")
    monkeypatch.setenv("PIS_DOCTOR_PROBE_NETWORK", "0")
    monkeypatch.setenv("PIS_PG_URL", "")


@pytest.fixture
def release_corpus(tmp_path: Path) -> AcceptanceCorpus:
    return build_acceptance_corpus(tmp_path / "corpus")


@pytest.fixture
def release_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReleaseEnv:
    """Scan, extract and understand the acceptance corpus through canonical code."""
    _isolate(tmp_path, monkeypatch)
    from src.archives.indexer import ArchiveIndexer
    from src.core.database import DatabaseManager
    from src.core.scan_service import ScanRequest, ScanService
    from src.core.volume import VolumeInfo
    from src.dedup import ContentHasher, VersionTracker
    from src.ingest.pipeline import IngestionPipeline
    from src.intel.pipeline import IntelPipeline
    from src.intelligence.semantic_search import SemanticSearchEngine

    corpus = build_acceptance_corpus(tmp_path / "corpus")
    root = corpus.root
    db = DatabaseManager(tmp_path / "release.db")

    scanned = ScanService(db).run(ScanRequest(
        root=root,
        volume=VolumeInfo(stable_key="release", device="release",
                          mountpoint=str(root), is_available=True)))
    assert scanned.status == "COMPLETED"

    # Index the archive so its members become first-class documents.
    from src.archives.inspector import ArchiveBudget
    indexer = ArchiveIndexer(db)
    with db.get_connection() as conn:
        row = conn.execute("SELECT id, path, volume_id FROM files WHERE extension='.zip'").fetchone()
    assert row is not None
    indexer.index_archive(int(row["id"]), str(row["path"]), budget=ArchiveBudget(),
                          volume_id=row["volume_id"])

    extracted = IngestionPipeline(db).run(min_size=1, max_size=50 * 1024 * 1024)
    assert extracted["counts"].get("EXTRACTED", 0) >= 10

    IntelPipeline(db).run(min_chars=10, include_members=True)
    ContentHasher(db).backfill(min_size=1, max_size=50 * 1024 * 1024, include_members=True)
    VersionTracker(db).build(include_members=False)

    generator = HashingEmbeddingGenerator(dim=64)
    engine = SemanticSearchEngine(db, embedding_gen=generator)
    engine.refresh(batch_size=128)

    return ReleaseEnv(root=tmp_path, corpus=corpus, db=db, generator=generator,
                      store_dir=tmp_path / "store", engine=engine)


@pytest.fixture
def release_db(release_env: ReleaseEnv) -> Any:
    return release_env.db
