"""Canonical UI for extraction issues, retries and format capabilities (M017).

Bounded, local-only, no destructive source action and no sensitive payloads.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def _db() -> Any:
    return st.session_state.db


def _pipeline() -> Any:
    from ..ingest.pipeline import IngestionPipeline
    if "m017_pipeline" not in st.session_state:
        st.session_state.m017_pipeline = IngestionPipeline(_db())
    return st.session_state.m017_pipeline


def _audit() -> Any:
    from ..intel import AuditTrail, IntelStore
    if "m017_audit" not in st.session_state:
        st.session_state.m017_audit = AuditTrail(IntelStore(_db()))
    return st.session_state.m017_audit


def render() -> None:
    st.header("🛠️ Ingestion & Coverage")
    st.caption(
        "Local-only extraction health: outcome taxonomy, retry queue and the "
        "format capability matrix. No cloud conversion, no destructive source change."
    )
    tab_issues, tab_caps = st.tabs(["Extraction issues", "Format capabilities"])
    with tab_issues:
        _render_issues()
    with tab_caps:
        _render_caps()


def _render_issues() -> None:
    pipe = _pipeline()
    queue = pipe.queue
    stats = queue.stats()
    cols = st.columns(4)
    cols[0].metric("Queued", f"{stats['total']:,}")
    cols[1].metric("Retryable pending", f"{stats['retryable_pending']:,}")
    cols[2].metric("Terminal classes", f"{sum(1 for k in stats['by_outcome'] if k not in ('TIMEOUT','TRANSIENT_ERROR','UNSUPPORTED_DEPENDENCY','OCR_FAILED')):,}")
    cols[3].metric("OCR", "on" if __import__('src.extractors.ocr', fromlist=['ocr_enabled']).ocr_enabled() else "off")

    c1, c2 = st.columns(2)
    limit = c1.number_input("Max documents this run", min_value=10, value=500, step=50)
    scope = c2.text_input("Root scope (optional)")
    c3, c4 = st.columns(2)
    if c3.button("Run extraction (bounded)", key="m017_run"):
        with st.spinner("Extracting..."):
            res = pipe.run(limit=int(limit), scope_prefix=scope or None)
        _audit().record("extraction_run", detail=f"attempted={res['attempted']}", sensitivity="normal")
        st.success(f"Attempted {res['attempted']}: {res['counts']}")
    if c4.button("Retry eligible", key="m017_retry"):
        with st.spinner("Retrying..."):
            res = pipe.run_retries(limit=int(limit))
        _audit().record("extraction_retry", detail=f"attempted={res['attempted']}", sensitivity="normal")
        st.success(f"Retried {res['attempted']}: {res['counts']}")

    if stats["by_outcome"]:
        st.markdown("**Outcome breakdown**")
        st.bar_chart(stats["by_outcome"])

    issues = queue.issues(limit=200)
    if not issues:
        st.info("No extraction issues recorded.")
        return
    st.markdown("**Issues**")
    for row in issues[:100]:
        missing = "dependency" in (row.get("detail") or "").lower() or row["outcome"] == "UNSUPPORTED_DEPENDENCY"
        label = (f"[{row['id']}] {row['outcome']} · ext {row.get('extension')} · attempts {row['attempts']}"
                 f"{' · optional dependency missing' if missing else ''}"
                 f"{' · retry after ' + str(row['retry_after']) if row.get('retry_after') else ''}")
        with st.expander(label):
            st.text(f"file id: {row['id']}")
            st.text(f"detail: {row.get('detail') or '-'}")
            st.text(f"terminal: {bool(row['terminal'])} · ignored: {bool(row['ignored'])}")
            b1, b2 = st.columns(2)
            if b1.button("Ignore / defer", key=f"ign-{row['id']}"):
                queue.ignore(int(row["id"]))
                st.rerun()
            if b2.button("Retry now", key=f"ret-{row['id']}"):
                with _db().get_connection() as conn:
                    conn.execute("UPDATE extraction_queue SET terminal=0, retry_after=NULL "
                                 "WHERE file_id=?", (int(row["id"]),))
                    conn.commit()
                pipe.extract_file(int(row["id"]), row["path"])
                st.rerun()


def _render_caps() -> None:
    from ..ingest.capabilities import capability_matrix
    matrix = capability_matrix()
    status_labels = {"SUPPORTED": "✅", "PARTIAL": "🟡", "OPTIONAL_DEPENDENCY_MISSING": "🟠",
                     "DEFERRED": "⏸️", "UNSUPPORTED": "⛔"}
    rows = []
    for f in matrix["formats"]:
        rows.append({"format": f["format"],
                     "status": f"{status_labels.get(f['status'], '')} {f['status']}",
                     "extensions": ", ".join(f["extensions"]),
                     "missing tools": ", ".join(f["missing_tools"]) or "—",
                     "note": f["note"]})
    st.dataframe(rows, use_container_width=True)
    st.markdown("**Local tools**")
    st.json(matrix["optional_dependencies"])
    st.markdown("**OCR**")
    st.json(matrix["ocr"])
