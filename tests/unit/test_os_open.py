"""Cross-platform open/reveal helpers (regression: Windows-only ``explorer``)."""
from __future__ import annotations

from pathlib import Path

import src.utils.os_open as os_open


def _recorder(calls: list[list[str]]):
    def _popen(args, *a, **k):  # noqa: ARG001 - signature compatibility
        calls.append(list(args))
        return object()

    return _popen


def _linux(monkeypatch) -> None:
    monkeypatch.setattr(os_open, "_is_windows", lambda: False)
    monkeypatch.setattr(os_open, "_is_macos", lambda: False)


def test_reveal_path_opens_parent_folder_on_linux(tmp_path: Path, monkeypatch) -> None:
    _linux(monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(os_open.subprocess, "Popen", _recorder(calls))
    target = tmp_path / "corpus" / "a.txt"
    target.parent.mkdir()
    target.write_text("x", encoding="utf-8")

    assert os_open.reveal_path(target) is True
    assert calls[-1] == ["xdg-open", str(target.parent)]


def test_reveal_path_opens_directory_itself(tmp_path: Path, monkeypatch) -> None:
    _linux(monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(os_open.subprocess, "Popen", _recorder(calls))
    assert os_open.reveal_path(tmp_path) is True
    assert calls[-1] == ["xdg-open", str(tmp_path)]


def test_open_path_uses_xdg_open_on_linux(tmp_path: Path, monkeypatch) -> None:
    _linux(monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(os_open.subprocess, "Popen", _recorder(calls))
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    assert os_open.open_path(target) is True
    assert calls[-1] == ["xdg-open", str(target)]


def test_helpers_never_raise_when_opener_is_missing(tmp_path: Path, monkeypatch) -> None:
    _linux(monkeypatch)

    def _missing(*_args, **_kwargs):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(os_open.subprocess, "Popen", _missing)
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    assert os_open.reveal_path(target) is False
    assert os_open.open_path(target) is False


def test_no_ui_module_hardcodes_windows_openers() -> None:
    """The UI must use ``os_open`` helpers, never raw ``explorer``/startfile."""
    root = Path(__file__).resolve().parents[2] / "src" / "ui"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "explorer" not in text, f"Windows-only opener in {path.name}"
        assert "os.startfile" not in text, f"Windows-only opener in {path.name}"


def test_interactive_table_uses_canonical_helper() -> None:
    source = (Path(__file__).resolve().parents[2] / "src" / "ui" / "interactive_table.py").read_text(
        encoding="utf-8"
    )
    assert "from ..utils.os_open import" in source
    assert "reveal_path" in source
    assert "open_path" in source
    assert "reveal_path(path)" in source
