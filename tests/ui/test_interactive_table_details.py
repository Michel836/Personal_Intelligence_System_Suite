"""The 👁️ action must actually render a details panel (not just set state)."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

ROW = {
    "id": 42,
    "filename": "facture.txt",
    "path": "/tmp/corpus/facture.txt",
    "size_bytes": 12_345,
    "extension": ".txt",
    "modified_at": "2024-01-02 12:00:00",
    "file_type": "document",
    "priority": "critical",
    "state": "ACTIVE",
    "content_extracted": 1,
    "content_text": "Facture ACME 1250 EUR — contenu de test.",
}


def _table_app(row: dict) -> None:
    import streamlit as st

    from src.ui.interactive_table import InteractiveTable

    st.session_state["test_row"] = row
    InteractiveTable(key_prefix="t").render(
        [st.session_state["test_row"]], title="Résultats", page_size=20,
        show_actions=True, show_export=False,
    )


def _click_view(at: AppTest) -> AppTest:
    for button in at.button:
        if button.key == "t_view_0":
            return button.click().run()
    raise AssertionError("view button not found")


def test_view_button_renders_metadata_and_preview() -> None:
    at = AppTest.from_function(_table_app, args=(ROW,)).run()
    assert not at.exception
    at = _click_view(at)
    assert not at.exception
    rendered = "\n".join(str(m.value) for m in at.markdown)
    assert "facture.txt" in rendered
    assert "critical" in rendered
    assert "/tmp/corpus" in rendered
    try:
        codes = "\n".join(str(block.value) for block in at.code)
    except AttributeError:  # pragma: no cover - older AppTest without .code
        codes = rendered
    assert "/tmp/corpus/facture.txt" in codes
    previews = [area.value for area in at.text_area]
    assert any("Facture ACME" in (value or "") for value in previews)


def test_view_button_without_content_explains_metadata_only() -> None:
    row = {**ROW, "content_text": None, "content_extracted": 0}
    at = AppTest.from_function(_table_app, args=(row,)).run()
    at = _click_view(at)
    captions = "\n".join(str(c.value) for c in at.caption)
    assert "Aucun contenu extrait" in captions
