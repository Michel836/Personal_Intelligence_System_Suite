"""Expert-user functional acceptance for the real Streamlit application.

Uses Streamlit's official widget-level harness (``streamlit.testing.v1.AppTest``)
to launch the actual app script, navigate every page, seed a temporary corpus via
the canonical scan service, and exercise search / recovery / persistence.

Skipped when Streamlit (a UI-only dependency) is unavailable, so the core
validation suite stays green in minimal environments.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.core.database import DatabaseManager  # noqa: E402
from src.core.scan_service import ScanRequest, ScanService  # noqa: E402
from src.core.volume import VolumeInfo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ui" / "app.py"

CONTENT = {
    "cancer.txt": "cancer immunotherapy study",
    "resume.txt": "candidat résumé professionnel",
}


@pytest.fixture()
def ui_db(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "ui.db"))
    return tmp_path


def _app(path: Path = APP) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=120).run()


def _nav(at: AppTest, page: str) -> AppTest:
    [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
    at.run()
    return at


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    (root / "Documents").mkdir(parents=True)
    (root / "Documents" / "cancer.txt").write_text(CONTENT["cancer.txt"], encoding="utf-8")
    (root / "Documents" / "resume.txt").write_text("candidat resume professionnel", encoding="utf-8")
    (root / "Documents" / "photo.jpg").touch()
    db = DatabaseManager()
    result = ScanService(db).run(
        ScanRequest(
            root=root,
            volume=VolumeInfo(stable_key="UI", device="UI", mountpoint=str(tmp_path), is_available=True),
        )
    )
    assert result.status == "COMPLETED", (result.status, result.error)
    rows = {r["filename"]: r for r in db.search_files(limit=100)}
    for name, text in CONTENT.items():
        assert name in rows, sorted(rows)
        db.update_content(rows[name]["id"], text)
    return root


def _search(at: AppTest, query: str, include_missing: bool = False) -> AppTest:
    [t for t in at.text_input if t.label == "Search query"][0].set_value(query)
    if include_missing:
        [c for c in at.checkbox if c.label == "Show missing files (recovery)"][0].set_value(True)
    [b for b in at.button if b.label == "🔍 Search"][0].click()
    at.run()
    return at


def _result_count(at: AppTest) -> int:
    for s in at.subheader:
        match = re.search(r"Search Results \((\d+) results\)", s.value)
        if match:
            return int(match.group(1))
    return 0


def _result_names(at: AppTest) -> list[str]:
    names: list[str] = []
    for markdown in at.markdown:
        names.extend(re.findall(r"\*\*(.+?)\*\*", markdown.value))
    return names


def test_all_pages_render_without_exception(ui_db: Path) -> None:
    options = list([r for r in _app().radio if r.label == "Navigation"][0].options)
    assert len(options) >= 13
    for page in options:
        at = _nav(_app(), page)
        assert not at.exception, f"{page}: {[e.message for e in at.exception]}"


def test_search_single_term(ui_db: Path, tmp_path: Path) -> None:
    _seed(tmp_path)
    at = _search(_nav(_app(), "🔍 Search"), "cancer")
    assert _result_count(at) == 1
    assert any("cancer.txt" in n for n in _result_names(at))


def test_search_multi_term_and_phrase(ui_db: Path, tmp_path: Path) -> None:
    _seed(tmp_path)
    at = _nav(_app(), "🔍 Search")
    assert _result_count(_search(at, "cancer immunotherapy")) == 1
    assert _result_count(_search(at, '"cancer immunotherapy"')) == 1
    assert _result_count(_search(at, "cancer zzzznope")) == 0


def test_search_unicode(ui_db: Path, tmp_path: Path) -> None:
    _seed(tmp_path)
    at = _search(_nav(_app(), "🔍 Search"), "résumé")
    assert _result_count(at) == 1
    assert any("resume.txt" in n for n in _result_names(at))


def test_search_malformed_does_not_crash(ui_db: Path, tmp_path: Path) -> None:
    _seed(tmp_path)
    at = _nav(_app(), "🔍 Search")
    for query in ["---", "*", "AND", 'foo"bar', "NEAR("]:
        at = _search(at, query)
        assert not at.exception, f"{query}: {[e.message for e in at.exception]}"


def test_recovery_toggle_reveals_missing(ui_db: Path, tmp_path: Path) -> None:
    root = _seed(tmp_path)
    (root / "Documents" / "photo.jpg").unlink()
    db = DatabaseManager()
    ScanService(db).run(
        ScanRequest(
            root=root,
            volume=VolumeInfo(stable_key="UI", device="UI", mountpoint=str(tmp_path), is_available=True),
        )
    )
    at = _nav(_app(), "🔍 Search")
    assert _result_count(_search(at, "photo")) == 0  # MISSING hidden by default
    at = _search(at, "photo", include_missing=True)
    assert _result_count(at) == 1
    assert any("photo.jpg" in n for n in _result_names(at))


def test_dashboard_renders_with_and_without_data(ui_db: Path, tmp_path: Path) -> None:
    assert not _nav(_app(), "📊 Dashboard").exception  # empty state
    _seed(tmp_path)
    assert not _nav(_app(), "📊 Dashboard").exception


def test_restart_persistence(ui_db: Path, tmp_path: Path) -> None:
    _seed(tmp_path)
    first = _search(_nav(_app(), "🔍 Search"), "cancer")
    assert _result_count(first) == 1

    # A brand-new session (application restart) sees the same persisted index.
    restarted = _search(_nav(_app(), "🔍 Search"), "cancer")
    assert _result_count(restarted) == 1


def test_ai_unavailable_degrades_gracefully(ui_db: Path) -> None:
    assert not _nav(_app(), "💬 AI Chat").exception


def test_final_uninterrupted_user_journey(ui_db: Path, tmp_path: Path) -> None:
    volume = VolumeInfo(stable_key="UI", device="UI", mountpoint=str(tmp_path), is_available=True)
    root = _seed(tmp_path)
    db = DatabaseManager()
    service = ScanService(db)

    # search filename + content after initial scan
    at = _search(_nav(_app(), "🔍 Search"), "cancer")
    assert _result_count(at) == 1
    at = _search(at, "immunotherapy")
    assert _result_count(at) == 1

    # modify + rescan -> refreshed metadata
    (root / "Documents" / "cancer.txt").write_text("cancer immunotherapy study extended", encoding="utf-8")
    service.run(ScanRequest(root=root, volume=volume))

    # rename + rescan -> stable id
    file_id = db.search_files(query="cancer")[0]["id"]
    (root / "Documents" / "cancer.txt").rename(root / "Documents" / "oncology.txt")
    service.run(ScanRequest(root=root, volume=volume))
    assert db.search_files(query="oncology")[0]["id"] == file_id

    # delete + rescan -> recovery view
    (root / "Documents" / "oncology.txt").unlink()
    service.run(ScanRequest(root=root, volume=volume))
    assert _result_count(_search(_nav(_app(), "🔍 Search"), "oncology")) == 0
    assert _result_count(_search(_nav(_app(), "🔍 Search"), "oncology", include_missing=True)) == 1

    # restart -> persisted index coherent, dashboard renders
    assert _result_count(_search(_nav(_app(), "🔍 Search"), "résumé")) == 1
    assert not _nav(_app(), "📊 Dashboard").exception
    assert not _nav(_app(), "👁️ File Viewer").exception
