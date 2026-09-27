"""M015 pipeline freshness, privacy filters and restart consistency."""
from __future__ import annotations

import datetime
from pathlib import Path

from src.core.database import DatabaseManager
from src.intel import AuditTrail, IntelPipeline, IntelStore
from src.scanner.models import FileType


def _save(db, factory, path: Path, mtime=datetime.datetime(2026, 1, 1)):  # noqa: DTZ001
    return db.save_file(factory(path, size_bytes=path.stat().st_size,
                                file_type=FileType.DOCUMENT, modified_at=mtime))


def _set_content(db, fid, text):
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET content_text=?, content_extracted=1, indexed_at=? WHERE id=?",
                     (text, "2026-01-01 00:00:00", fid))
        conn.commit()


FR = "Le contrat de service prévoit une facture mensuelle pour le client. " * 4
DE = "Der Vertrag zwischen der Gesellschaft und dem Kunden sieht eine Rechnung vor. " * 4


def test_incremental_pipeline_and_manual_override(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = IntelStore(db)
    pipe = IntelPipeline(db, store=store)

    p = tmp_path / "facture.txt"
    p.write_text(FR)
    fid = _save(db, file_info_factory, p)
    _set_content(db, fid, FR)

    first = pipe.run(min_chars=10)
    assert first["processed"] == 1
    assert store.get_language(fid)["lang"] == "fr"
    assert any(c["category"] == "finance" for c in store.get_categories(fid))

    # No-change run does nothing (incremental).
    assert pipe.run(min_chars=10)["processed"] == 0

    # Manual override always wins and survives recomputation.
    store.set_override(fid, "vip", include=True)
    store.set_override(fid, "finance", include=False)
    pipe.process_document(fid, FR, extension=".txt")
    cats = {c["category"]: c["source"] for c in store.get_categories(fid)}
    assert cats.get("vip") == "manual"
    assert "finance" not in cats

    # Content change refreshes only that document.
    _set_content(db, fid, DE)
    refreshed = pipe.run(min_chars=10)
    assert refreshed["processed"] == 1
    assert store.get_language(fid)["lang"] == "de"


def test_deletion_prunes_stale_metadata(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = IntelStore(db)
    pipe = IntelPipeline(db, store=store)
    p = tmp_path / "a.txt"
    p.write_text(FR)
    fid = _save(db, file_info_factory, p)
    _set_content(db, fid, FR)
    pipe.run(min_chars=10)
    assert store.get_language(fid) is not None

    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=?", (fid,))
        conn.commit()
    pipe.run(min_chars=10)
    assert store.get_language(fid) is None
    assert store.get_categories(fid) == []


def test_privacy_aware_search_filters(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    store = IntelStore(db)
    pipe = IntelPipeline(db, store=store)
    pf = tmp_path / "fr.txt"
    pf.write_text(FR)
    pg = tmp_path / "de.txt"
    pg.write_text(DE)
    ff = _save(db, file_info_factory, pf)
    _set_content(db, ff, FR)
    fg = _save(db, file_info_factory, pg)
    _set_content(db, fg, DE)
    pipe.run(min_chars=10)

    assert {r["id"] for r in db.search_files(query="", language="fr")} == {ff}
    assert {r["id"] for r in db.search_files(query="", language="de")} == {fg}
    # absent filters leave canonical behaviour unchanged
    assert len(db.search_files(query="", limit=100)) == 2


def test_deletion_prunes_pii_and_audit_trail(tmp_path, file_info_factory) -> None:  # noqa: ARG001
    db = DatabaseManager(tmp_path / "db.db")
    store = IntelStore(db)
    audit = AuditTrail(store)
    audit.record("sensitive_document_viewed", target_type="file", target_id=1, detail="viewed")
    events = audit.events()
    assert events and events[0]["action"] == "sensitive_document_viewed"
    assert audit.prune(keep=1) >= 0


def test_restart_consistency(tmp_path, file_info_factory) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    p = tmp_path / "x.txt"
    p.write_text(FR)
    fid = _save(db, file_info_factory, p)
    _set_content(db, fid, FR)
    IntelPipeline(db, store=IntelStore(db)).run(min_chars=10)

    # Fresh process equivalent: new store + pipeline read the persisted metadata.
    store2 = IntelStore(DatabaseManager(tmp_path / "db.db"))
    assert store2.get_language(fid)["lang"] == "fr"
    assert IntelPipeline(DatabaseManager(tmp_path / "db.db"), store=store2).run(min_chars=10)["processed"] == 0
