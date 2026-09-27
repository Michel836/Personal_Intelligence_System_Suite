"""Galaxy & Topics UI acceptance through the real Streamlit app (M020)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ui" / "app.py"
PAGE = "🌌 Galaxy & Topics"


@pytest.fixture(autouse=True)
def ui_env(galaxy_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIS_DB_PATH", str(galaxy_env.db.db_path))
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(galaxy_env.base_dir))
    monkeypatch.setenv("PIS_LAUNCH_PROFILE", "full")
    monkeypatch.setenv("PIS_REMOTE_CONTENT_POLICY", "never")
    monkeypatch.setenv("PIS_DOCTOR_PROBE_NETWORK", "0")


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=180).run()


def _nav(at: AppTest, page: str) -> AppTest:
    [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
    at.run()
    return at


def test_galaxy_page_is_navigable_and_renders() -> None:
    at = _app()
    assert PAGE in list([r for r in at.radio if r.label == "Navigation"][0].options)
    at = _nav(at, PAGE)
    assert not at.exception, [e.message for e in at.exception]


def test_galaxy_build_button_produces_summary() -> None:
    at = _nav(_app(), PAGE)
    build = [b for b in at.button if b.label == "🌀 Build galaxy"]
    assert build, [b.label for b in at.button]
    build[0].click()
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert {m.label for m in at.metric} >= {"Tier", "Points", "Input", "Clusters"}
