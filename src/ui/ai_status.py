"""Compact AI backend status surface (M012-A).

Renders the active AI mode, providers, hardware tier and remote-content policy.
Never displays API keys or secrets.
"""
from __future__ import annotations


def ai_status_lines(service=None, *, cheap: bool = True) -> dict:
    """Return a diagnostics-safe status dict (also used by tests).

    ``cheap=True`` (default) avoids constructing providers, so rendering AI
    status never loads a local embedding model.
    """
    if service is None:
        from ..ai.providers.service import get_ai_service

        service = get_ai_service()
    return service.status(cheap=cheap)


def render_ai_status(service=None, *, expanded: bool = False) -> None:
    import streamlit as st

    status = ai_status_lines(service, cheap=True)
    cfg = status.get("config", {})
    llm = status.get("llm", {})
    emb = status.get("embeddings", {})
    gpu = status.get("gpu", {})

    with st.expander("🤖 AI backend status", expanded=expanded):
        cols = st.columns(3)
        cols[0].metric("AI mode", str(cfg.get("mode", "?")))
        cols[1].metric("Remote policy", str(cfg.get("content_policy", "never")))
        cols[2].metric("Hardware tier", str(status.get("hardware_tier", "?")))

        from ..core.launch_profile import current_profile

        tier = str(status.get("hardware_tier", "lite"))
        recommended = {"lite": "LITE", "balanced": "SMART", "performance": "FULL"}.get(tier, "SMART")
        st.caption(
            f"Active profile: {current_profile().value.upper()} · "
            f"recommended for this hardware tier: {recommended}"
        )

        def _describe(entry: dict) -> str:
            return (f"{entry.get('provider', '?')} · {entry.get('model') or '—'} · "
                    f"{'remote' if entry.get('remote') else 'local'} · "
                    f"{'available' if entry.get('available') else 'unavailable'}")

        st.write(f"**LLM:** {_describe(llm)}")
        st.write(f"**Embeddings:** {_describe(emb)}")
        st.caption(
            f"GPU: {gpu.get('name') or 'none'} ({gpu.get('vram_gb', 0)} GB) · "
            f"RAM {gpu.get('ram_gb', 0)} GB · "
            f"API configured: {cfg.get('api_configured', False)} "
            f"(key {'set' if cfg.get('api_key_present') else 'absent'})"
        )
        usage = (status.get("usage") or {}).get("totals", {})
        if usage.get("requests"):
            st.caption(
                f"Usage: {usage.get('requests', 0)} requests · "
                f"{usage.get('total_tokens', 0)} tokens · "
                f"{usage.get('completion_tokens', 0)} completion"
            )
