"""Extraction outcome taxonomy + retry queue tests (M017)."""
from __future__ import annotations

from src.core.database import DatabaseManager
from src.ingest.queue_store import ExtractionQueue
from src.ingest.taxonomy import (
    Outcome,
    backoff_seconds,
    classify_error,
    is_retryable,
    is_terminal,
)


def test_classify_error_mapping() -> None:
    assert classify_error("operation timed out") == Outcome.TIMEOUT.value
    assert classify_error("file is encrypted") == Outcome.ENCRYPTED.value
    assert classify_error("PDF is malformed") == Outcome.MALFORMED.value
    assert classify_error("7z not installed") == Outcome.UNSUPPORTED_DEPENDENCY.value
    assert classify_error("No suitable extractor found") == Outcome.UNSUPPORTED_FORMAT.value
    assert classify_error("file too large") == Outcome.RESOURCE_LIMIT.value
    assert classify_error("no text") == Outcome.NO_TEXT.value
    assert classify_error(None) == Outcome.PERMANENT_ERROR.value


def test_terminal_and_retryable() -> None:
    assert is_terminal(Outcome.MALFORMED.value)
    assert is_terminal(Outcome.ENCRYPTED.value)
    assert not is_terminal(Outcome.TIMEOUT.value)
    assert is_retryable(Outcome.TIMEOUT.value, attempts=1)
    assert not is_retryable(Outcome.TIMEOUT.value, attempts=3)
    assert not is_retryable(Outcome.MALFORMED.value, attempts=1)


def test_backoff_is_bounded() -> None:
    assert backoff_seconds(1) == 60
    assert backoff_seconds(2) == 300
    assert backoff_seconds(3) == 1500
    assert backoff_seconds(99) == 3600


def test_queue_records_retries_and_ignores(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    # minimal file row
    with db.get_connection() as conn:
        conn.execute("INSERT INTO files (id, path, filename, size_bytes, modified_at, state, document_kind) "
                     "VALUES (1, '/x/a.doc', 'a.doc', 10, '2026-01-01', 'ACTIVE', 'PHYSICAL_FILE')")
        conn.commit()
    q = ExtractionQueue(db)
    r1 = q.record(1, Outcome.TIMEOUT.value, detail="timed out")
    assert r1["attempts"] == 1 and r1["terminal"] is False and r1["retry_after"]
    r2 = q.record(1, Outcome.TIMEOUT.value, detail="timed out")
    assert r2["attempts"] == 2
    # terminal outcome overrides
    q.record(1, Outcome.MALFORMED.value, detail="corrupt")
    assert q.retryable() == []
    assert q.stats()["by_outcome"].get("MALFORMED") == 1
    q.clear(1)
    assert q.stats()["total"] == 0

    # ignore marks terminal and hides from retryable
    q.record(1, Outcome.TIMEOUT.value, detail="tz")
    q.ignore(1)
    assert q.retryable() == []
    assert q.issues(include_ignored=True)


def test_ocr_required_is_visible_but_not_auto_retried(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    with db.get_connection() as conn:
        conn.execute("INSERT INTO files (id, path, filename, size_bytes, modified_at, state, document_kind) "
                     "VALUES (1, '/x/scan.pdf', 'scan.pdf', 10, '2026-01-01', 'ACTIVE', 'PHYSICAL_FILE')")
        conn.commit()
    q = ExtractionQueue(db)
    q.record(1, Outcome.OCR_REQUIRED.value, detail="ocr disabled")
    # Blocked on opt-in: shown in issues, but not swept into automatic retries.
    assert q.retryable() == []
    assert q.issues()
    assert q.stats()["retryable_pending"] == 1



def test_queue_prunes_missing_files(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    with db.get_connection() as conn:
        conn.execute("INSERT INTO files (id, path, filename, size_bytes, modified_at, state, document_kind) "
                     "VALUES (1, '/x/a.doc', 'a.doc', 10, '2026-01-01', 'MISSING', 'PHYSICAL_FILE')")
        conn.commit()
    q = ExtractionQueue(db)
    q.record(1, Outcome.TIMEOUT.value)
    assert q.prune_missing() == 1
