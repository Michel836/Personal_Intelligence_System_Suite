"""Profile-gated, lazy-loading acceptance for the canonical app (M012-B2)."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ai.providers.service import reset_ai_service  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ui" / "app.py"

CORE_PAGES = [
    "🚀 Scanner",
    "🔍 Search",
    "🎯 Advanced Search",
    "🏷️ Tags & Favorites",
    "📊 Dashboard",
    "👁️ File Viewer",
]
ADVANCED_PAGES = ["🧠 AI Search", "💬 AI Chat", "🌌 Visualizations", "🤖 Advanced AI", "☁️ Cloud Sync"]


@pytest.fixture()
def profile_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.delenv("PIS_LAUNCH_PROFILE", raising=False)
    monkeypatch.delenv("PIS_FEATURE_AI_CHAT", raising=False)
    reset_ai_service()
    yield monkeypatch
    reset_ai_service()


def _run() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=180).run()


def _nav(at: AppTest) -> list[str]:
    return [r for r in at.radio if r.label == "Navigation"][0].options


def test_lite_navigation_is_core_only(profile_env) -> None:
    profile_env.setenv("PIS_LAUNCH_PROFILE", "lite")
    at = _run()
    options = _nav(at)
    assert not at.exception
    for page in CORE_PAGES:
        assert page in options
    for page in ADVANCED_PAGES:
        assert page not in options


def test_smart_and_full_expose_all_pages(profile_env) -> None:
    for profile in ("smart", "full"):
        profile_env.setenv("PIS_LAUNCH_PROFILE", profile)
        options = _nav(_run())
        for page in CORE_PAGES + ADVANCED_PAGES:
            assert page in options, f"{profile}: {page}"


def test_feature_env_can_extend_lite(profile_env) -> None:
    profile_env.setenv("PIS_LAUNCH_PROFILE", "lite")
    profile_env.setenv("PIS_FEATURE_AI_CHAT", "1")
    options = _nav(_run())
    assert "💬 AI Chat" in options


def test_default_profile_is_full_for_direct_start(profile_env) -> None:
    profile_env.delenv("PIS_LAUNCH_PROFILE", raising=False)
    options = _nav(_run())
    assert "🧠 AI Search" in options and "💬 AI Chat" in options


def test_lite_core_pages_render(profile_env) -> None:
    profile_env.setenv("PIS_LAUNCH_PROFILE", "lite")
    at = _run()
    for page in CORE_PAGES:
        [r for r in at.radio if r.label == "Navigation"][0].set_value(page)
        at.run()
        assert not at.exception, f"{page}: {[e.message for e in at.exception]}"


def test_lite_startup_does_not_import_heavy_ml(tmp_path: Path) -> None:
    """Fresh-process check: LITE startup must not import torch/sentence-transformers."""
    script = textwrap.dedent(
        f"""
        import os, sys, tempfile
        os.environ["PIS_LAUNCH_PROFILE"] = "lite"
        os.environ["PIS_DB_PATH"] = r"{tmp_path / 'fresh.db'}"
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(r"{APP}", default_timeout=180).run()
        print("TORCH", "torch" in sys.modules)
        print("ST", "sentence_transformers" in sys.modules)
        print("EXC", bool(at.exception))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "TORCH False" in proc.stdout, proc.stdout[-2000:]
    assert "ST False" in proc.stdout, proc.stdout[-2000:]
    assert "EXC False" in proc.stdout, proc.stdout[-2000:]
