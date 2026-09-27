"""Compatibility shim for the historical SMART launcher (M012-B2).

The historical module picker was replaced by the SMART launch profile, which is
hardware-aware and lazily exposes every capability on the canonical app::

    python launchers/smart_launcher.py [--port 8504]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROFILE = "smart"


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

    st.error("This launcher is obsolete: `streamlit run launchers/smart_launcher.py` is no longer supported.")
    st.markdown("Use the unified launcher instead:")
    st.code(f"python -m src.launcher --profile {PROFILE}", language="bash")
    st.code("scripts/run_smart.sh", language="bash")
    st.info("SMART keeps hardware-aware AUTO defaults and exposes all capabilities lazily.")
    st.stop()


if _under_streamlit():  # pragma: no cover - only under `streamlit run`
    _render_migration()
else:
    from src.launcher import main

    raise SystemExit(main(["--profile", PROFILE, *sys.argv[1:]]))
