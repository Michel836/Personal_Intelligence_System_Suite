"""Ingestion & Coverage UI acceptance through the real Streamlit app (M017).

Exercises the capability/status view and the extraction error workflow:
render, bounded run, issue surfacing and ignore, all against a temporary DB.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.core.database import DatabaseManager  # noqa: E402
from src.core.scan_service import ScanRequest, ScanService  # noqa: E402
from src.core.volume import VolumeInfo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ui" / "app.py"
PAGE = "🛠️ Ingestion & Coverage"


@pytest.fixture()
def ingest_db(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "ui-ingest.db"))
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "good.eml").write_bytes(
        b"From: a@b.com\r\nSubject: Hello\r\nMessage-ID: <1@b>\r\n\r\nBody text.\r\n")
    (root / "bad.epub").write_text("not a zip container")
    result = ScanService(DatabaseManager()).run(
        ScanRequest(root=root,
                    volume=VolumeInfo(stable_key="UI-ING", device="UI-ING",
                                      mountpoint=str(tmp_path), is_available=True)))
    assert result.status == "COMPLETED", (result.status, result.error)
    return root


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=120).run()


def _nav(at: AppTest, page: str) -> AppTest:
    [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
    at.run()
    return at


def test_ingestion_page_is_navigable_and_renders(ingest_db: Path) -> None:
    assert ingest_db.is_dir()
    at = _app()
    assert PAGE in list([r for r in at.radio if r.label == "Navigation"][0].options)
    at = _nav(at, PAGE)
    assert not at.exception, [e.message for e in at.exception]
    # capability/status view is rendered as a dataframe
    assert len(at.dataframe) >= 1
    assert {m.label for m in at.metric} >= {"Queued", "Retryable pending"}


def test_extraction_run_surfaces_issue_and_ignore(ingest_db: Path) -> None:
    assert (ingest_db / "good.eml").exists()
    at = _nav(_app(), PAGE)
    assert not at.exception
    run = [b for b in at.button if b.label == "Run extraction (bounded)"]
    assert run, [b.label for b in at.button]
    run[0].click()
    at.run()
    assert not at.exception, [e.message for e in at.exception]

    db = DatabaseManager()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT file_id, outcome, ignored FROM extraction_queue").fetchall()
    assert rows, "the malformed EPUB must be queued"
    assert any(r["outcome"] == "MALFORMED" for r in rows)

    ignore = [b for b in at.button if b.label == "Ignore / defer"]
    assert ignore, [b.label for b in at.button]
    ignore[0].click()
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    with db.get_connection() as conn:
        ignored = conn.execute("SELECT COUNT(*) FROM extraction_queue WHERE ignored=1").fetchone()[0]
    assert ignored >= 1
