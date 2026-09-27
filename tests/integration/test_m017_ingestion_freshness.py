"""M017 ingestion freshness, threading and graph integration."""
from __future__ import annotations

import zipfile
from pathlib import Path

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.graph import RelationService
from src.ingest.pipeline import IngestionPipeline
from src.ingest.queue_store import ExtractionQueue
from src.ingest.taxonomy import Outcome
from src.ingest.thread_store import EmailThreadStore


def _scan(db, root: Path) -> None:
    ScanService(db).run(ScanRequest(root=root, batch_size=100))


def _id(db, path: Path) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM files WHERE path=?", (str(path),)).fetchone()[0])


def _write_epub(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/c.xhtml", f"<html><body><p>{text}</p></body></html>")


def test_pipeline_extracts_and_queues_failures(tmp_path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.eml").write_bytes(
        b"From: a@b.com\r\nSubject: Hello\r\nMessage-ID: <1@b>\r\n\r\nEmail body text.\r\n")
    _write_epub(root / "book.epub", "EPUB body text.")
    (root / "bad.epub").write_text("this is not a zip container")
    db = DatabaseManager(tmp_path / "db.db")
    _scan(db, root)

    pipe = IngestionPipeline(db)
    stats = pipe.run(min_size=1, max_size=10_000_000)
    assert stats["attempted"] == 3
    assert stats["counts"].get(Outcome.EXTRACTED.value) == 2
    assert stats["counts"].get(Outcome.MALFORMED.value) == 1
    # extracted text is searchable through canonical FTS
    assert db.search_files("Email body text")
    assert db.search_files("EPUB body text")
    # terminal failure is in the queue and not retryable
    q = pipe.queue
    assert q.stats()["by_outcome"].get(Outcome.MALFORMED.value) == 1
    assert q.retryable() == []
    # already-successful docs are not reprocessed
    assert pipe.run(min_size=1, max_size=10_000_000)["attempted"] == 0
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_email_thread_relation_and_graph(tmp_path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "1.eml").write_bytes(
        b"From: a@b.com\r\nSubject: Root\r\nMessage-ID: <root@x>\r\n\r\nFirst message.\r\n")
    (root / "2.eml").write_bytes(
        b"From: c@d.com\r\nSubject: Re: Root\r\nMessage-ID: <reply@x>\r\n"
        b"In-Reply-To: <root@x>\r\nReferences: <root@x>\r\n\r\nReply message.\r\n")
    db = DatabaseManager(tmp_path / "db.db")
    _scan(db, root)
    IngestionPipeline(db).run(min_size=1, max_size=10_000_000)
    threads = EmailThreadStore(db)
    assert threads.stats()["messages"] == 2
    one = _id(db, root / "1.eml")
    replies = threads.replies_for(one)
    assert replies and any(r["id"] == _id(db, root / "2.eml") for r in replies)
    rels = RelationService(db).relations_for(one, types=["EMAIL_REPLY_TO"])
    assert rels and all(r.directed and r.type == "EMAIL_REPLY_TO" for r in rels)


def test_retry_and_prune(tmp_path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.eml").write_bytes(b"From: a@b.com\r\nSubject: S\r\n\r\nBody.\r\n")
    db = DatabaseManager(tmp_path / "db.db")
    _scan(db, root)
    fid = _id(db, root / "a.eml")
    q = ExtractionQueue(db)
    q.record(fid, Outcome.TIMEOUT.value, detail="timed out")
    assert q.stats()["retryable_pending"] == 1
    # backoff means the retry is not due yet; force it due
    with db.get_connection() as conn:
        conn.execute("UPDATE extraction_queue SET retry_after='2000-01-01 00:00:00' WHERE file_id=?", (fid,))
        conn.commit()
    assert len(q.retryable()) == 1
    # a retry attempt clears the queue on success
    IngestionPipeline(db, queue=q).run_retries()
    assert q.stats()["total"] == 0

    # deleted files are pruned from the queue
    q.record(fid, Outcome.TIMEOUT.value)
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=?", (fid,))
        conn.commit()
    assert q.prune_missing() >= 1


def test_restart_consistency(tmp_path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.eml").write_bytes(b"From: a@b.com\r\nSubject: S\r\n\r\nBody.\r\n")
    db = DatabaseManager(tmp_path / "db.db")
    _scan(db, root)
    IngestionPipeline(db).run(min_size=1, max_size=1_000_000)
    # fresh objects read the persisted state; no reprocessing
    db2 = DatabaseManager(tmp_path / "db.db")
    assert IngestionPipeline(db2).run(min_size=1, max_size=1_000_000)["attempted"] == 0
    assert EmailThreadStore(db2).stats()["messages"] == 1
