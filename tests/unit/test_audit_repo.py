"""Regression tests for ``scripts/audit_repo.py`` marker detection.

These guard the M002 fix that stopped ordinary ``placeholder=`` keyword
arguments (Streamlit widgets) from being reported as TODO/placeholder debt,
while keeping genuine TODO/FIXME/XXX/HACK/"not implemented"/prose placeholder
markers.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
_AUDIT_PATH = ROOT / "scripts" / "audit_repo.py"


def _load_audit_repo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_repo", _AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_placeholder_keyword_argument_is_not_flagged(tmp_path: Path) -> None:
    audit = _load_audit_repo()
    audit.ROOT = tmp_path  # type: ignore[attr-defined]
    sample = tmp_path / "sample.py"
    sample.write_text(
        'st.text_input("Path", placeholder="C:\\\\Data")\n'
        'st.text_area(placeholder = "describe it")\n',
        encoding="utf-8",
    )

    assert audit.markers([sample]) == []


def test_genuine_markers_are_still_flagged(tmp_path: Path) -> None:
    audit = _load_audit_repo()
    audit.ROOT = tmp_path  # type: ignore[attr-defined]
    sample = tmp_path / "sample.py"
    sample.write_text(
        "# TODO: implement proper tracking\n"
        "# FIXME handle the empty case\n"
        "# XXX unsafe assumption\n"
        "# HACK work around the bug\n"
        "# not implemented in the fast scanner\n"
        '"""Pause scanning (placeholder for compatibility)."""\n',
        encoding="utf-8",
    )

    hits = audit.markers([sample])
    texts = [hit["text"] for hit in hits]

    assert len(hits) == 6
    assert any("TODO" in text for text in texts)
    assert any("FIXME" in text for text in texts)
    assert any("XXX" in text for text in texts)
    assert any("HACK" in text for text in texts)
    assert any("not implemented" in text for text in texts)
    assert any("placeholder for compatibility" in text for text in texts)
