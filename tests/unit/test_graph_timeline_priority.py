"""Timeline provenance + explainable priority tests (M016)."""
from __future__ import annotations

import datetime
from pathlib import Path

from src.core.database import DatabaseManager
from src.dedup import ContentHasher, DedupStore, ExactDuplicateEngine, VersionTracker
from src.graph import DocumentGraph, TimelineService, compute_priority, rank_documents
from src.intel import IntelPipeline, IntelStore
from src.scanner.models import FileInfo, FileType
from src.tags.tag_manager import TagManager


def _add(db, path: Path, content: str, mtime=None):
    path.write_text(content)
    fi = FileInfo(path=path, filename=path.name, size_bytes=path.stat().st_size,
                  modified_at=mtime or datetime.datetime(2026, 1, 1), extension=path.suffix,  # noqa: DTZ001
                  file_type=FileType.DOCUMENT)
    fid = db.save_file(fi)
    db.update_content(fid, content)
    return fid


def test_timeline_provenance_and_grouping(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, tmp_path / "a.txt", "facture contrat " * 20, datetime.datetime(2026, 1, 10))  # noqa: DTZ001
    _add(db, tmp_path / "b.txt", "facture contrat " * 20, datetime.datetime(2026, 2, 20))  # noqa: DTZ001
    svc = TimelineService(db)
    by_month = svc.events(group="month")
    assert by_month["date_source"] == "modified_at"
    assert by_month["confidence"] == "HIGH"
    assert {b["bucket"] for b in by_month["buckets"]} == {"2026-01", "2026-02"}
    for ev in by_month["events"]:
        assert ev["date_source"] == "modified_at" and ev["provenance"]
    summary = svc.sources_summary()
    assert summary["modified_at"]["available"] == 2
    assert summary["created_at"]["available"] == 0  # never invented


def test_version_date_source(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, tmp_path / "rapport_2025-03-04.txt", "rapport " * 30)
    svc = TimelineService(db)
    ev = svc.events(source="version_date", group="day")
    assert ev["date_source"] == "version_date" and ev["confidence"] == "MEDIUM"
    assert any(e["date"] == "2025-03-04" for e in ev["events"])


def test_priority_user_signals_dominate_and_pii_is_not_a_signal(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    a = _add(db, tmp_path / "a.txt", "plain document " * 30)
    b = _add(db, tmp_path / "b.txt", "another plain document " * 30)
    tm = TagManager(str(tmp_path / "db.db"))
    tm.add_to_favorites(a)
    store = IntelStore(db)
    IntelPipeline(db, store=store).run(min_chars=10)

    pa = compute_priority(db, a, intel_store=store, tag_manager=tm)
    pb = compute_priority(db, b, intel_store=store, tag_manager=tm)
    assert pa["score"] > pb["score"]
    assert pa["user_signals_present"] is True
    assert any(c["signal"] == "favorite" and c["value"] == 1.0 for c in pa["components"])
    assert not any("pii" in c["signal"] for c in pa["components"])


def test_priority_query_match_and_duplicate_penalty(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    ds = DedupStore(db)
    a = _add(db, tmp_path / "report_final.txt", "report body " * 30)
    b = _add(db, tmp_path / "report_final_copy.txt", "report body " * 30)
    ExactDuplicateEngine(db, ds, ContentHasher(db, ds)).hash_duplicate_candidates(min_size=1)
    VersionTracker(db, ds).build()
    store = IntelStore(db)
    IntelPipeline(db, store=store).run(min_chars=10)
    matched = compute_priority(db, a, query="report final", intel_store=store, dedup_store=ds)
    assert any(c["signal"] == "query_match" and c["value"] == 1.0 for c in matched["components"])
    ranked = rank_documents(db, [a, b], intel_store=store, dedup_store=ds)
    assert {r["file_id"] for r in ranked} == {a, b}


def test_graph_priority_and_timeline_facade(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    ds = DedupStore(db)
    a = _add(db, tmp_path / "x.txt", "hello " * 40)
    store = IntelStore(db)
    IntelPipeline(db, store=store).run(min_chars=10)
    g = DocumentGraph(db, intel_store=store, dedup_store=ds)
    assert g.priority(a)["file_id"] == a
    assert g.timeline_events(group="year")["count"] >= 1
