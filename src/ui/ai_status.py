"""Compact AI backend status surface (M012-A).

Renders the active AI mode, providers, hardware tier and remote-content policy.
Never displays API keys or secrets.
"""
from __future__ import annotations

from typing import Any


def ai_status_lines(service=None, *, cheap: bool = True) -> dict:
    """Return a diagnostics-safe status dict (also used by tests).

    ``cheap=True`` (default) avoids constructing providers, so rendering AI
    status never loads a local embedding model.
    """
    if service is None:
        from ..ai.providers.service import get_ai_service

        service = get_ai_service()
    return service.status(cheap=cheap)


def render_ai_status(service=None, *, expanded: bool = False, db=None) -> None:
    """Render backend status, semantic coverage and embedding-job controls.

    ``db`` is the canonical ``DatabaseManager``; when provided, the widget
    shows the real coverage for this database and lets the operator start or
    stop the resumable background embedding job.
    """
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

        if db is not None:
            _render_coverage(st, db)


def _render_coverage(st: Any, db: Any) -> None:
    """Semantic coverage + resumable embedding job controls (point 7)."""
    from ..core.coverage import extraction_coverage, semantic_coverage
    from ..intelligence.embedding_job import EmbeddingJob

    st.markdown("---")
    st.markdown("**📈 Couverture sémantique**")
    try:
        coverage = semantic_coverage(db)
        extracted = extraction_coverage(db)
    except Exception as exc:  # noqa: BLE001 - status must never break the UI
        st.caption(f"couverture indisponible : {exc}")
        return

    st.progress(
        min(max(coverage["percent"] / 100.0, 0.0), 1.0),
        text=(f"{coverage['percent']:.1f} % · {coverage['embedded']:,} / "
              f"{coverage['eligible']:,} documents"),
    )
    st.caption(
        f"Extraction : {extracted['percent']:.1f} % "
        f"({extracted['extracted']:,}/{extracted['active_files']:,}) · "
        f"en attente d'embedding : {coverage['pending']:,}"
    )

    job = EmbeddingJob(db)
    state = job.status(live=False)
    running = bool(state.get("running"))
    label = state.get("status", "IDLE")
    detail = f"Job : {label}"
    if state.get("embedded"):
        detail += f" · {state['embedded']:,} traités ce run"
    if state.get("error"):
        detail += f" · {state['error']}"
    st.caption(detail)

    col_a, col_b = st.columns(2)
    if col_a.button("▶️ Embeddings", key="pis_embed_start", disabled=running,
                    use_container_width=True):
        result = job.start_background()
        if result.get("started"):
            st.success(f"Worker démarré (pid {result.get('pid')}).")
        else:
            st.warning(f"Démarrage impossible : {result.get('reason')}")
        st.rerun()
    if col_b.button("⏹️ Stop", key="pis_embed_stop", disabled=not running,
                    use_container_width=True):
        job.request_stop()
        st.info("Arrêt demandé ; l'état reste reprenable.")
        st.rerun()

    if state.get("log"):
        with st.expander("Journal du job"):
            try:
                with open(state["log"], encoding="utf-8", errors="ignore") as fh:
                    tail = fh.readlines()[-40:]
                st.code("".join(tail) or "(vide)")
            except OSError as exc:
                st.caption(f"journal indisponible : {exc}")
