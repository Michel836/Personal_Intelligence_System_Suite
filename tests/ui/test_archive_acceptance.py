"""Archive application acceptance through the real Streamlit app (M009J.26)."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.archives.indexer import ArchiveIndexer  # noqa: E402
from src.core.database import DatabaseManager  # noqa: E402
from src.core.scan_service import ScanRequest, ScanService  # noqa: E402
from src.core.volume import VolumeInfo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ui" / "app.py"


@pytest.fixture()
def archive_corpus(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "ui-arch.db"))
    root = tmp_path / "corpus"
    docs = root / "Documents"
    docs.mkdir(parents=True)
    archive = docs / "backup.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("reports/quarterly.txt", "quarterly archive facture budget")
        zf.writestr("notes.md", "meeting notes archive member")
    db = DatabaseManager()
    result = ScanService(db).run(
        ScanRequest(
            root=root,
            volume=VolumeInfo(stable_key="UI-ARC", device="UI-ARC", mountpoint=str(tmp_path), is_available=True),
        )
    )
    assert result.status == "COMPLETED", (result.status, result.error)
    pid = next(r["id"] for r in db.search_files(None) if r["filename"] == "backup.zip")
    ArchiveIndexer(db).index_archive(pid, str(archive))
    return root


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=120).run()


def _nav(at: AppTest, page: str) -> AppTest:
    [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
    at.run()
    return at


def test_archive_member_search_and_viewer(archive_corpus) -> None:
    db = DatabaseManager()
    member = next(m for m in db.search_files("facture") if m["document_kind"] == "ARCHIVE_MEMBER")
    assert member["path"].endswith("!/reports/quarterly.txt")

    at = _app()
    assert not at.exception

    at = _nav(at, "🔍 Search")
    [ti for ti in at.text_input if "earch" in (ti.label or "")][0].set_value("facture")
    at.run()
    assert not at.exception

    at = _nav(at, "👁️ File Viewer")
    assert not at.exception

    at = _nav(at, "🔄 Auto-Extract")
    assert not at.exception
