"""Canonical UI for the M016 timeline, relationship graph and prioritization.

Bounded by design (node/edge caps), provenance-aware, privacy-masked, and never
phrased as a human/social relationship. No destructive action.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from ..graph import (
    DATE_SOURCES,
    DEFAULT_NEIGHBORHOOD_TYPES,
    OPTIONAL_TYPES,
    DocumentGraph,
    RelationType,
    plotly_network,
)


def _db() -> Any:
    return st.session_state.db


def _graph() -> Any:
    if "m016_graph" not in st.session_state:
        intel_store = st.session_state.get("intel_store")
        dedup_store = st.session_state.get("dedup_store")
        st.session_state.m016_graph = DocumentGraph(
            _db(), intel_store=intel_store, dedup_store=dedup_store)
    return st.session_state.m016_graph


def render() -> None:
    st.header("🧭 Timeline & Relationship Graph")
    st.caption(
        "Local-only, provenance-aware timeline and bounded relationship graph over the "
        "existing duplicate/version/entity/category/archive data. Shared entities mean "
        "both documents mention them — no human relationship is inferred. No destructive action."
    )
    tab_timeline, tab_graph, tab_priority = st.tabs(["Timeline", "Relationship graph", "Prioritized documents"])
    with tab_timeline:
        _render_timeline(_graph())
    with tab_graph:
        _render_graph(_graph())
    with tab_priority:
        _render_priority(_graph())


def _render_timeline(g: DocumentGraph) -> None:
    st.subheader("Document timeline")
    c1, c2, c3 = st.columns(3)
    source = c1.selectbox("Date source", list(DATE_SOURCES.keys()),
                          format_func=lambda s: f"{s} ({DATE_SOURCES[s][0]})")
    group = c2.selectbox("Group by", ["day", "week", "month", "year"], index=2)
    scope = c3.text_input("Root scope (optional)")
    c4, c5, c6 = st.columns(3)
    language = c4.text_input("Language filter (e.g. fr)")
    category = c5.text_input("Category filter (e.g. finance)")
    pii_mode = c6.selectbox("Sensitivity", ["(any)", "only PII", "exclude high-sensitivity"])
    filters: dict[str, Any] = {"source": source, "group": group}
    if scope:
        filters["scope_prefix"] = scope
    if language:
        filters["language"] = language
    if category:
        filters["category"] = category
    if pii_mode == "only PII":
        filters["has_pii"] = True
    elif pii_mode == "exclude high-sensitivity":
        filters["exclude_high_sensitivity"] = True
    try:
        res = g.timeline_events(**filters)
    except Exception as exc:  # noqa: BLE001 - missing M015 tables etc.
        st.info(f"Timeline unavailable: {exc}")
        return
    st.caption(f"Date source: **{res['date_source']}** · confidence **{res['confidence']}** · "
               f"provenance: {res['provenance']}")
    if not res["buckets"]:
        st.info("No events in this range/filter.")
        return
    try:
        import plotly.graph_objects as go  # type: ignore[import-untyped]
        fig = go.Figure(go.Bar(x=[b["bucket"] for b in res["buckets"]],
                               y=[b["count"] for b in res["buckets"]]))
        fig.update_layout(height=320, margin={"l": 10, "r": 10, "t": 10, "b": 10},
                          xaxis_title=group, yaxis_title="documents")
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        st.bar_chart({b["bucket"]: b["count"] for b in res["buckets"]})
    st.write(f"{res['count']} events (showing up to the query limit)")
    if res["events"]:
        st.dataframe(res["events"][:200], use_container_width=True)
    with st.expander("Available date sources"):
        st.json(g.timeline.sources_summary())


def _render_graph(g: DocumentGraph) -> None:
    st.subheader("Selected-document neighborhood")
    c1, c2, c3 = st.columns(3)
    file_id = c1.number_input("Document id", min_value=1, value=1, step=1, key="m016_doc")
    depth = c2.selectbox("Depth", [1, 2], index=0)
    semantic = c3.checkbox("Include semantic relations", value=False)
    all_types = [t.value for t in RelationType]
    selected = st.multiselect(
        "Relation types", all_types,
        default=[t.value for t in DEFAULT_NEIGHBORHOOD_TYPES])
    c4, c5 = st.columns(2)
    max_nodes = c4.slider("Max nodes", 10, 200, 50, 10)
    max_edges = c5.slider("Max edges", 10, 500, 120, 10)
    high_degree = [t.value for t in OPTIONAL_TYPES]
    if any(t in high_degree for t in selected):
        st.warning("High-degree relation types are bounded by the node/edge caps.")
    if st.button("Build graph", key="m016_build"):
        res: Any = g.neighborhood(int(file_id), types=selected, depth=int(depth),
                             max_nodes=int(max_nodes), max_edges=int(max_edges),
                             semantic=bool(semantic))
        st.session_state["m016_nb"] = res
    res = st.session_state.get("m016_nb")
    if not res:
        st.info("Enter a document id and build its bounded neighborhood.")
        return
    st.caption(f"nodes {res['metrics']['nodes']} · edges {res['metrics']['edges']} · "
               f"components {res['metrics']['components']} · max degree {res['metrics']['max_degree']} · "
               f"center PageRank {res['metrics'].get('center_pagerank')}")
    fig = plotly_network(res["nodes"], res["edges"], max_nodes=int(max_nodes))
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("**Edges**")
    for e in res["edges"][:200]:
        st.text(f"{e['type']} · {e['source']} → {e['target']} · score={e['score']} · "
                f"{e.get('evidence')}")
    with st.expander("📁 Dossier from this bounded neighborhood"):
        st.caption("Only the nodes shown above (already filtered by the graph service) "
                   "are offered; hidden/sensitive nodes are never added silently.")
        try:
            from src.ui.reports_page import add_to_dossier_widget
            node_ids = [int(n["id"]) for n in res["nodes"] if str(n.get("id", "")).isdigit()]
            add_to_dossier_widget(st.session_state.db, node_ids, key_prefix="m016_neighborhood")
        except Exception as exc:  # noqa: BLE001 - optional action
            st.caption(f"Dossier action unavailable: {type(exc).__name__}")

    st.divider()
    st.subheader("Entity / document graph")
    c6, c7, c8 = st.columns(3)
    min_docs = c6.number_input("Minimum documents per entity", min_value=1, value=2)
    max_entities = c7.slider("Max entities", 10, 300, 100, 10)
    co_occurrence = c8.checkbox("Include entity co-occurrence (bounded)", value=False)
    if st.button("Build entity graph", key="m016_ent"):
        eg: Any = g.entity_graph(min_docs=int(min_docs), max_entities=int(max_entities),
                            max_edges=1000, co_occurrence=bool(co_occurrence))
        st.session_state["m016_ent"] = eg
    eg = st.session_state.get("m016_ent")
    if eg:
        st.caption(f"entities {eg['stats']['entities']} · edges {eg['stats']['edges']}")
        with st.expander("Edges"):
            for e in eg["edges"][:300]:
                st.text(f"{e['type']} · {e['source']} → {e['target']} · {e.get('evidence')}")


def _render_priority(g: DocumentGraph) -> None:
    st.subheader("Explainable prioritization")
    st.caption("Transparent weighted signals. User signals dominate; PII/sensitivity is a filter, "
               "never an importance signal.")
    c1, c2 = st.columns(2)
    file_id = c1.number_input("Document id", min_value=1, value=1, step=1, key="m016_prio")
    query = c2.text_input("Query (optional)", key="m016_prio_query")
    if st.button("Explain score", key="m016_explain"):
        res = g.priority(int(file_id), query=query or None)
        st.metric("Priority score", res["score"])
        if res["user_signals_present"]:
            st.success("User signals present — they dominate weak inferred signals.")
        st.table(res["components"])
        st.caption(res["note"])
    st.divider()
    st.subheader("Rank a bounded set")
    ids_raw = st.text_input("Comma-separated document ids", key="m016_ids")
    if ids_raw and st.button("Rank", key="m016_rank"):
        try:
            ids = [int(x) for x in ids_raw.replace(" ", "").split(",") if x]
        except ValueError:
            st.error("Invalid id list")
            return
        ranked = g.rank(ids[:100], query=query or None)
        for r in ranked:
            st.text(f"[{r['file_id']}] score={r['score']} "
                    f"{'· user-signal' if r['user_signals_present'] else ''}")
