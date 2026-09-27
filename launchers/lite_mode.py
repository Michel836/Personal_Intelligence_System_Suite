"""Compatibility shim for the historical LITE launcher (M012-B2).

The standalone LITE Streamlit UI was replaced by a launch profile on the single
canonical app.  This script keeps the historical entrypoint working as a thin
wrapper::

    python launchers/lite_mode.py [--port 8510]

It forwards to ``python -m src.launcher --profile lite``.  Running it through
``streamlit run`` (the obsolete documented command) prints a migration message
instead of silently launching the wrong app.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROFILE = "lite"


def _under_streamlit() -> bool:
    try:
        from streamlit.runtime import exists
    except Exception:  # streamlit missing -> definitely a plain python run
        return False
    try:
        return bool(exists())
    except Exception:  # pragma: no cover - defensive
        return False


def _render_migration() -> None:
    import streamlit as st

    st.error("This launcher is obsolete: `streamlit run launchers/lite_mode.py` is no longer supported.")
    st.markdown("Use the unified launcher instead:")
    st.code(f"python -m src.launcher --profile {PROFILE}", language="bash")
    st.code("scripts/run_lite.sh", language="bash")
    st.info("All profiles run the same canonical app (src/ui/app.py); LITE just applies lightweight defaults.")
    st.stop()


if _under_streamlit():  # pragma: no cover - only under `streamlit run`
    _render_migration()
else:
    from src.launcher import main

    raise SystemExit(main(["--profile", PROFILE, *sys.argv[1:]]))
