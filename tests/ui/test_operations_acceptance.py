"""Operations & System UI acceptance through the real Streamlit app (M019)."""
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
PAGE = "🧰 Operations & System"


@pytest.fixture()
def ops_db(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "ui-ops.db"))
    monkeypatch.setenv("PIS_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("PIS_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("PIS_DOCTOR_PROBE_NETWORK", "0")
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.txt").write_text("operations ui", encoding="utf-8")
    result = ScanService(DatabaseManager()).run(ScanRequest(
        root=root,
        volume=VolumeInfo(stable_key="OPS", device="OPS", mountpoint=str(tmp_path),
                          is_available=True)))
    assert result.status == "COMPLETED"
    return root


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=120).run()


def _nav(at: AppTest, page: str) -> AppTest:
    [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
    at.run()
    return at


def test_operations_page_is_navigable_and_renders(ops_db: Path) -> None:
    assert ops_db.is_dir()
    at = _app()
    assert PAGE in list([r for r in at.radio if r.label == "Navigation"][0].options)
    at = _nav(at, PAGE)
    assert not at.exception, [e.message for e in at.exception]
    assert {m.label for m in at.metric} >= {"Status", "Files"}


def test_doctor_runs_from_ui(ops_db: Path) -> None:
    assert (ops_db / "a.txt").exists()
    at = _nav(_app(), PAGE)
    run = [b for b in at.button if b.label == "Run doctor"]
    assert run, [b.label for b in at.button]
    run[0].click()
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert len(at.dataframe) >= 1
