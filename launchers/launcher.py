"""Compatibility shim for the historical FULL launcher (M012-B2).

The historical classic/modern chooser was replaced by the FULL launch profile on
the canonical app::

    python launchers/launcher.py [--port 8501]

The modern UI (``src/ui/modern_app.py``) is not part of the launch profiles; it
remains available directly via ``streamlit run src/ui/modern_app.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROFILE = "full"


def _under_streamlit() -> bool:
    try:
        from streamlit.runtime import exists
    except Exception:
        return False
    try:
        return bool(exists())
    except Exception:  # pragma: no cover - defensive
        return False


def _render_migration() -> None:
    import streamlit as st

    st.error("This launcher is obsolete: `streamlit run launchers/launcher.py` is no longer supported.")
    st.markdown("Use the unified launcher instead:")
    st.code(f"python -m src.launcher --profile {PROFILE}", language="bash")
    st.code("scripts/run_full.sh", language="bash")
    st.info("Every profile now runs the canonical app (src/ui/app.py) with lazy loading.")
    st.stop()


if _under_streamlit():  # pragma: no cover - only under `streamlit run`
    _render_migration()
else:
    from src.launcher import main

    raise SystemExit(main(["--profile", PROFILE, *sys.argv[1:]]))
