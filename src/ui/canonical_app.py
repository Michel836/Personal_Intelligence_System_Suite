"""Canonical Streamlit entrypoint.

The historical ``src.ui.app`` still contains legacy page implementations.  This
entrypoint keeps the mature application surface but replaces the unsafe legacy
Scanner page with the production-safe implementation.
"""
from __future__ import annotations

from src.ui import app as legacy_app
from src.ui.safe_scanner_page import scanner_page as safe_scanner_page

legacy_app.scanner_page = safe_scanner_page


if __name__ == "__main__":  # pragma: no cover - Streamlit entrypoint
    legacy_app.main()
