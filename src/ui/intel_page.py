"""Canonical UI surface for document intelligence + local privacy (M015).

Language, categories, entities and PII are shown as metadata. PII is masked by
default; the redaction preview is non-destructive and never writes to source
files. No destructive action is offered.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def _db() -> Any:
    return st.session_state.db


def _store() -> Any:
    from ..intel import IntelStore

    if "intel_store" not in st.session_state:
        st.session_state.intel_store = IntelStore(_db())
    return st.session_state.intel_store


def _pipeline() -> Any:
    from ..intel import IntelPipeline

    if "intel_pipeline" not in st.session_state:
        st.session_state.intel_pipeline = IntelPipeline(_db(), store=_store())
    return st.session_state.intel_pipeline


def _audit() -> Any:
    from ..intel import AuditTrail

    if "intel_audit" not in st.session_state:
        st.session_state.intel_audit = AuditTrail(_store())
    return st.session_state.intel_audit


def render() -> None:
    st.header("🧠 Document Intelligence & Privacy")
    st.caption(
        "Local-only language, entity, category and PII metadata. PII is masked by "
        "default; the redaction preview never modifies source files. "
        "No account, RBAC, telemetry or external API."
    )
    store = _store()
    stats = store.stats()
    cols = st.columns(4)
    cols[0].metric("Documents analysed", f"{stats['documents']:,}")
    cols[1].metric("Languages", f"{len(stats['languages']):,}")
    cols[2].metric("PII types", f"{len(stats['pii_types']):,}")
    cols[3].metric("Entity types", f"{len(stats['entity_types']):,}")

    tab_overview, tab_doc, tab_search, tab_redact, tab_audit = st.tabs(
        ["Overview", "Document", "Filtered search", "Redaction preview", "Audit trail"]
    )
    with tab_overview:
        _render_overview(store)
    with tab_doc:
        _render_document(store)
    with tab_search:
        _render_search(_db(), store)
    with tab_redact:
        _render_redaction(_db(), store)
    with tab_audit:
        _render_audit(store)


def _render_overview(store: Any) -> None:
    st.subheader("Run local analysis")
    c1, c2 = st.columns(2)
    limit = c1.number_input("Max documents (bounded)", min_value=100, value=5000, step=1000)
    min_chars = c2.number_input("Minimum content characters", min_value=1, value=50)
    if st.button("Analyse documents", key="m015_run"):
        audit = _audit()
        with st.spinner("Detecting language, entities, categories and PII..."):
            res = _pipeline().run(limit=int(limit), min_chars=int(min_chars), include_members=False)
        audit.record("intel_pipeline_run", detail=f"processed={res['processed']}", sensitivity="normal")
        st.success(f"Processed {res['processed']:,} documents ({res['docs_per_sec']} docs/s).")
    stats = store.stats()
    st.markdown("**Language distribution**")
    st.bar_chart(stats["languages"]) if stats["languages"] else st.info("No language data yet.")
    st.markdown("**Category distribution**")
    st.bar_chart(stats["categories"]) if stats["categories"] else st.info("No category data yet.")
    st.markdown("**PII by severity**")
    st.bar_chart(stats["pii_severity"]) if stats["pii_severity"] else st.info("No PII data yet.")
    st.markdown("**Entity types**")
    st.bar_chart(stats["entity_types"]) if stats["entity_types"] else st.info("No entity data yet.")


def _render_document(store: Any) -> None:
    st.subheader("Document metadata")
    file_id = st.number_input("Document id", min_value=1, value=1, step=1, key="m015_doc_id")
    audit = _audit()
    if st.button("Load metadata", key="m015_load"):
        st.session_state["m015_doc"] = {
            "language": store.get_language(int(file_id)),
            "categories": store.get_categories(int(file_id)),
            "entities": store.get_entities(int(file_id)),
            "pii": store.get_pii(int(file_id)),
        }
        audit.record("sensitive_document_viewed", target_type="file", target_id=int(file_id),
                     detail="metadata", sensitivity="high" if store.get_pii(int(file_id)) else "normal")
    doc = st.session_state.get("m015_doc")
    if not doc:
        st.info("Enter a document id and load its metadata.")
        return
    lang = doc["language"]
    if lang:
        st.markdown(f"**Language:** `{lang['lang']}` (confidence {lang['confidence']:.2f}, {lang['method']})")
    st.markdown("**Categories:** " + (", ".join(
        f"`{c['category']}` ({c['source']})" for c in doc["categories"]) or "—"))
    st.markdown("**Entities:** " + (", ".join(
        f"`{e['entity_type']}` {e['display_value'] or ''}" for e in doc["entities"][:30]) or "—"))
    if doc["pii"]:
        st.warning("Possible sensitive content detected (masked).")
        for p in doc["pii"]:
            st.text(f"{p['pii_type']} · {p['severity']} · {p['masked']} · ×{p['count']}")
    else:
        st.success("No PII detected by the conservative detectors.")


def _render_search(db: Any, store: Any) -> None:
    from ..intel import filter_options, search_with_intelligence

    st.subheader("Privacy-aware search")
    opts = filter_options(store)
    query = st.text_input("Query", key="m015_query")
    c1, c2, c3 = st.columns(3)
    language = c1.selectbox("Language", ["(any)"] + opts["languages"])
    category = c2.selectbox("Category", ["(any)"] + opts["categories"])
    pii_mode = c3.selectbox("Sensitive content", ["(any)", "only PII", "exclude PII", "exclude high-sensitivity"])
    filters: dict[str, Any] = {}
    if language != "(any)":
        filters["language"] = language
    if category != "(any)":
        filters["category"] = category
    if pii_mode == "only PII":
        filters["has_pii"] = True
    elif pii_mode == "exclude PII":
        filters["has_pii"] = False
    elif pii_mode == "exclude high-sensitivity":
        filters["exclude_high_sensitivity"] = True
    if st.button("Search", key="m015_search"):
        _audit().record("pii_filter_search", detail="+".join(filters) or "plain", sensitivity="high")
        results = search_with_intelligence(db, query or None, limit=50, **filters)
        st.write(f"{len(results)} results")
        for r in results:
            st.text(f"[{r['id']}] {r.get('filename')} · {r.get('extension')}")


def _render_redaction(db: Any, store: Any) -> None:
    from ..intel import redacted_preview

    st.subheader("Non-destructive redaction preview")
    st.caption("Reads the stored extracted text, masks it for display only. The source file is never modified.")
    file_id = st.number_input("Document id", min_value=1, value=1, step=1, key="m015_redact_id")
    if st.button("Preview", key="m015_preview"):
        with db.get_connection() as conn:
            row = conn.execute("SELECT content_text FROM files WHERE id=?", (int(file_id),)).fetchone()
        text = (row["content_text"] if row else "") or ""
        preview = redacted_preview(text, store=store)
        _audit().record("redacted_preview", target_type="file", target_id=int(file_id),
                        detail="preview", sensitivity="high")
        if not preview["findings"]:
            st.info("No PII detected; preview would be unchanged.")
        st.code(preview["redacted"] or "(empty)")
        if preview["truncated"]:
            st.caption("Preview truncated to a bounded length.")


def _render_audit(_store: Any) -> None:
    st.subheader("Local audit trail")
    st.caption("Operational audit of sensitive actions. No document content or secrets are recorded.")
    events = _audit().events(limit=100)
    if not events:
        st.info("No audit events yet.")
        return
    for e in events:
        st.text(f"{e['ts']} · {e['action']} · {e['target_type'] or '-'}:{e['target_id'] or '-'} "
                f"· {e['sensitivity']} · {e['detail'] or ''}")
