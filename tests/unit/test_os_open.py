"""Cross-platform open/reveal helpers (M012-B2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.utils import os_open


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.raise_on_call = False

    def __call__(self, args: list[str]) -> object:
        if self.raise_on_call:
            raise OSError("boom")
        self.calls.append(list(args))
        return object()


@pytest.fixture()
def popen(monkeypatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(os_open.subprocess, "Popen", rec)
    return rec


def test_open_path_linux_uses_xdg_open(popen: _Recorder, monkeypatch) -> None:
    monkeypatch.setattr(os_open.sys, "platform", "linux")
    assert os_open.open_path("/tmp/report.pdf") is True
    assert popen.calls == [["xdg-open", "/tmp/report.pdf"]]


def test_reveal_path_linux_uses_parent(popen: _Recorder, monkeypatch) -> None:
    monkeypatch.setattr(os_open.sys, "platform", "linux")
    assert os_open.reveal_path("/tmp/data/report.pdf") is True
    assert popen.calls == [["xdg-open", "/tmp/data"]]


def test_reveal_path_linux_directory_uses_itself(popen: _Recorder, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os_open.sys, "platform", "linux")
    assert os_open.reveal_path(tmp_path) is True
    assert popen.calls == [["xdg-open", str(tmp_path)]]


def test_open_path_macos(popen: _Recorder, monkeypatch) -> None:
    monkeypatch.setattr(os_open.sys, "platform", "darwin")
    assert os_open.open_path("/tmp/report.pdf") is True
    assert popen.calls == [["open", "/tmp/report.pdf"]]


def test_open_path_windows_uses_startfile(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(os_open.sys, "platform", "win32")
    monkeypatch.setattr(os_open.os, "startfile", lambda p: calls.append(p), raising=False)
    assert os_open.open_path("C:/tmp/report.pdf") is True
    assert calls == ["C:/tmp/report.pdf"]


def test_open_path_never_raises(popen: _Recorder, monkeypatch) -> None:
    monkeypatch.setattr(os_open.sys, "platform", "linux")
    popen.raise_on_call = True
    assert os_open.open_path("/tmp/missing.pdf") is False
    assert os_open.reveal_path("/tmp/missing.pdf") is False


def test_no_hardcoded_windows_opener_in_canonical_app() -> None:
    app = Path(__file__).resolve().parents[2] / "src" / "ui" / "app.py"
    text = app.read_text(encoding="utf-8")
    assert "explorer /select" not in text
    assert "os.startfile" not in text


def test_platform_predicates() -> None:
    assert os_open._is_windows() is sys.platform.startswith("win")
    assert os_open._is_macos() is (sys.platform == "darwin")
