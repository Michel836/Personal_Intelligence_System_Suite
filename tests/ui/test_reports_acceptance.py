"""Dossiers & Reports UI acceptance through the real Streamlit app (M018)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.core.database import DatabaseManager  # noqa: E402
from src.core.scan_service import ScanRequest, ScanService  # noqa: E402
from src.core.volume import VolumeInfo  # noqa: E402
from src.reports.dossiers import DossierService  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ui" / "app.py"
PAGE = "📁 Dossiers & Reports"


@pytest.fixture()
def reports_db(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "ui-reports.db"))
    monkeypatch.setenv("PIS_EXPORT_DIR", str(tmp_path / "exports"))
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "cancer.txt").write_text("cancer immunotherapy study", encoding="utf-8")
    (root / "other.txt").write_text("unrelated weather notes", encoding="utf-8")
    db = DatabaseManager()
    result = ScanService(db).run(ScanRequest(
        root=root,
        volume=VolumeInfo(stable_key="UI-REP", device="UI-REP", mountpoint=str(tmp_path),
                          is_available=True)))
    assert result.status == "COMPLETED"
    for row in db.search_files(None, limit=10):
        db.update_content(int(row["id"]), Path(row["path"]).read_text())
    return root


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=120).run()


def _nav(at: AppTest, page: str) -> AppTest:
    [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
    at.run()
    return at


def _normalize_formatted_selectboxes(at: AppTest) -> None:
    """Work around Streamlit 1.28 AppTest serializing format_func labels as options."""
    for selectbox in at.selectbox:
        if selectbox.label == "Privacy mode" and selectbox.options:
            selectbox.set_value(selectbox.options[0])


def test_reports_page_is_navigable_and_renders(reports_db: Path) -> None:
    assert reports_db.is_dir()
    at = _app()
    assert PAGE in list([r for r in at.radio if r.label == "Navigation"][0].options)
    at = _nav(at, PAGE)
    assert not at.exception, [e.message for e in at.exception]


def test_create_dossier_through_ui(reports_db: Path) -> None:
    assert (reports_db / "cancer.txt").exists()
    at = _nav(_app(), PAGE)
    assert not at.exception
    name = [t for t in at.text_input if t.label == "Name"]
    assert name, [t.label for t in at.text_input]
    name[0].set_value("UI dossier")
    submit = [b for b in at.button if b.label == "Create dossier"]
    assert submit, [b.label for b in at.button]
    _normalize_formatted_selectboxes(at)
    submit[0].click()
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    dossiers = DossierService(DatabaseManager()).list_dossiers()
    assert any(d["name"] == "UI dossier" for d in dossiers), dossiers
