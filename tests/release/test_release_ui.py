"""Release UI smoke: every canonical page renders for the acceptance corpus (M021)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ui.app import _navigation_pages  # noqa: E402

APP = str(Path(__file__).resolve().parents[2] / "src" / "ui" / "app.py")


@pytest.fixture(autouse=True)
def _ui_release_env(release_env):  # noqa: ARG001 - fixture sets the isolated env
    return release_env


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=180).run()


def _nav_options(at: AppTest) -> list[str]:
    return list([r for r in at.radio if r.label == "Navigation"][0].options)


def _nav(at: AppTest, page: str) -> AppTest:
    [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
    at.run()
    return at


def test_every_full_profile_page_renders_without_exception() -> None:
    at = _app()
    options = _nav_options(at)
    assert options, "navigation must expose pages"
    failures: list[str] = []
    for page in options:
        at = _nav(at, page)
        if at.exception:
            failures.append(f"{page}: {[e.message for e in at.exception]}")
    assert not failures, failures


def test_profile_gating_for_galaxy_page(monkeypatch) -> None:
    monkeypatch.setenv("PIS_LAUNCH_PROFILE", "full")
    full = _app()
    assert "🌌 Galaxy & Topics" in _nav_options(full)

    monkeypatch.setenv("PIS_LAUNCH_PROFILE", "lite")
    lite = _app()
    assert "🌌 Galaxy & Topics" not in _nav_options(lite)
    assert "🔍 Search" in _nav_options(lite)


def test_navigation_pages_matches_profile_contract(monkeypatch) -> None:
    monkeypatch.setenv("PIS_LAUNCH_PROFILE", "lite")
    lite_pages = _navigation_pages()
    assert "🔍 Search" in lite_pages
    assert "🌌 Galaxy & Topics" not in lite_pages
    monkeypatch.setenv("PIS_LAUNCH_PROFILE", "full")
    assert "🌌 Galaxy & Topics" in _navigation_pages()
