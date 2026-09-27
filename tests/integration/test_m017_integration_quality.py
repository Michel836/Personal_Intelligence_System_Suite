"""M017 incremental freshness, intelligence and privacy integration.

Complements ``test_m017_ingestion_freshness`` with a modified-email re-ingestion
cycle, the M015 intelligence hand-off and the local-only privacy guarantees of
the extraction queue and audit trail.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.ingest.pipeline import IngestionPipeline
from src.ingest.queue_store import ExtractionQueue
from src.ingest.taxonomy import Outcome
from src.ingest.thread_store import EmailThreadStore
from src.intel import AuditTrail, IntelPipeline, IntelStore


def _scan(db: DatabaseManager, root: Path) -> None:
    ScanService(db).run(ScanRequest(root=root, batch_size=100))


def _id(db: DatabaseManager, path: Path) -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT id FROM files WHERE path=?", (str(path),)).fetchone()[0])


def _eml(subject: str, body: str, *, msg_id: str = "<m@x>",
         in_reply_to: str | None = None) -> bytes:
    headers = ["From: sender@example.com", f"Subject: {subject}", f"Message-ID: {msg_id}"]
    if in_reply_to:
        headers += [f"In-Reply-To: {in_reply_to}", f"References: {in_reply_to}"]
    return ("\r\n".join(headers) + "\r\n\r\n" + body + "\r\n").encode("utf-8")


def test_modified_email_is_reingested_incrementally(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    mail = root / "a.eml"
    mail.write_bytes(_eml("Freshness", "ALPHAEMAILTOKEN body"))
    db = DatabaseManager(tmp_path / "db.db")
    _scan(db, root)
    pipe = IngestionPipeline(db)
    assert pipe.run(min_size=1, max_size=1_000_000)["counts"].get(Outcome.EXTRACTED.value) == 1
    assert db.search_files("ALPHAEMAILTOKEN")

    # A modified message invalidates the stale text at scan time.
    mail.write_bytes(_eml("Freshness", "BETAEMAILTOKEN changed and longer body"))
    _scan(db, root)
    with db.get_connection() as conn:
        row = conn.execute("SELECT content_extracted, content_text FROM files WHERE path=?",
                           (str(mail),)).fetchone()
    assert row["content_extracted"] == 0
    assert row["content_text"] is None
    assert not db.search_files("ALPHAEMAILTOKEN")

    # Re-ingestion is incremental: only the changed message is attempted.
    assert pipe.run(min_size=1, max_size=1_000_000)["counts"].get(Outcome.EXTRACTED.value) == 1
    assert db.search_files("BETAEMAILTOKEN")
    assert not db.search_files("ALPHAEMAILTOKEN")
    # The thread store upserts rather than duplicating the message.
    assert EmailThreadStore(db).stats()["messages"] == 1
    assert pipe.run(min_size=1, max_size=1_000_000)["attempted"] == 0


def test_email_intelligence_language_and_masked_pii(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    body = (
        "Bonjour, je vous confirme le rendez-vous à Lyon. "
        "Merci de me joindre au +33 6 12 34 56 78 ou par courriel "
        "jean.dupont@example.com. Cordialement."
    )
    mail = root / "note.eml"
    mail.write_bytes(_eml("Rendez-vous", body))
    db = DatabaseManager(tmp_path / "db.db")
    _scan(db, root)
    IngestionPipeline(db).run(min_size=1, max_size=1_000_000)
    fid = _id(db, mail)

    stats = IntelPipeline(db).run(force=True)
    assert stats["processed"] == 1, stats
    store = IntelStore(db)
    language = store.get_language(fid)
    assert language is not None and language["lang"]
    findings = store.get_pii(fid)
    assert findings, "email address / phone should be classified"
    with db.get_connection() as conn:
        masked = " ".join(
            str(r[0] or "") for r in conn.execute(
                "SELECT masked FROM doc_pii WHERE file_id=?", (fid,)).fetchall())
    # Only masked values and fingerprints persist; the raw address never does.
    assert "jean.dupont@example.com" not in masked


def test_queue_and_audit_never_store_sensitive_payloads(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "good.eml").write_bytes(
        _eml("Contact", "Reach jean.dupont@example.com and call +33 6 12 34 56 78."))
    (root / "bad.epub").write_text("not a zip container")
    db = DatabaseManager(tmp_path / "db.db")
    _scan(db, root)

    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="DEBUG")
    try:
        IngestionPipeline(db).run(min_size=1, max_size=1_000_000)
    finally:
        logger.remove(sink)

    assert not any("jean.dupont@example.com" in m for m in messages)
    assert not any("+33 6 12 34 56 78" in m for m in messages)

    queue = ExtractionQueue(db)
    issues = queue.issues(include_ignored=True)
    assert issues  # the malformed EPUB is queued
    for row in issues:
        detail = row.get("detail") or ""
        assert len(detail) <= 160
        assert "jean.dupont@example.com" not in detail
        assert "Reach jean.dupont" not in detail

    audit = AuditTrail(IntelStore(db))
    audit.record("extraction_run", detail="attempted=2")
    events = audit.events()
    assert events
    assert not any("jean.dupont@example.com" in (e.get("detail") or "") for e in events)
