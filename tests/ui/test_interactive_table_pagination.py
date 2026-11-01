"""Pagination controls: next/previous and rows-per-page."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _paged_app() -> None:
    import streamlit as st

    from src.ui.interactive_table import InteractiveTable

    rows = [
        {
            "id": i,
            "filename": f"file_{i:02d}.txt",
            "path": f"/tmp/corpus/file_{i:02d}.txt",
            "size_bytes": 100 + i,
            "extension": ".txt",
            "modified_at": "2024-01-02 12:00:00",
            "file_type": "document",
            "priority": "medium",
            "state": "ACTIVE",
            "content_extracted": 0,
            "content_text": None,
        }
        for i in range(1, 46)
    ]
    st.session_state["rows"] = rows
    InteractiveTable(key_prefix="p").render(
        st.session_state["rows"], title="Résultats", page_size=20,
        show_actions=True, show_export=False,
    )


def _markdown(at: AppTest) -> str:
    return "\n".join(str(node.value) for node in at.markdown)


def _button(at: AppTest, key: str):
    return [button for button in at.button if button.key == key][0]


def test_next_and_previous_switch_pages() -> None:
    at = AppTest.from_function(_paged_app).run()
    first = _markdown(at)
    assert "file_01.txt" in first
    assert "file_21.txt" not in first

    at = _button(at, "p_next").click().run()
    second = _markdown(at)
    assert "file_21.txt" in second
    assert "file_01.txt" not in second

    at = _button(at, "p_prev").click().run()
    assert "file_01.txt" in _markdown(at)


def test_page_size_can_show_all_results() -> None:
    at = AppTest.from_function(_paged_app).run()
    selector = [box for box in at.selectbox if box.label == "Résultats par page"][0]
    at = selector.set_value(50).run()
    rendered = _markdown(at)
    assert "file_01.txt" in rendered
    assert "file_45.txt" in rendered
    # One page is enough now: the page slider is hidden.
    assert not [slider for slider in at.slider if slider.label == "Page"]


def test_slider_selects_a_page() -> None:
    at = AppTest.from_function(_paged_app).run()
    slider = [node for node in at.slider if node.label == "Page"][0]
    at = slider.set_value(3).run()
    rendered = _markdown(at)
    assert "file_41.txt" in rendered
    assert "file_45.txt" in rendered
    assert "file_01.txt" not in rendered
