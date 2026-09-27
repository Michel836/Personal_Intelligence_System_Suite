"""Galaxy & Topics UI (M020).

Canonical app only. Bounded, local-only, no destructive source action. The page
drives the same :class:`~src.galaxy.service.GalaxyService` as the CLI/API/bench,
so no data pipeline is duplicated here and no raw PII is rendered.
"""
from __future__ import annotations

import importlib
from typing import Any, cast

import streamlit as st

SCOPE_OPTIONS = ["all", "search", "category", "language", "date", "entity",
                 "dossier", "prefix", "file_ids"]
METHOD_OPTIONS = ["pca", "svd", "umap", "tsne"]
COLOR_OPTIONS = ["cluster", "category", "language", "extension", "priority",
                 "sensitivity", "year"]
GROUP_OPTIONS = ["day", "week", "month", "year"]


def _db() -> Any:
    return st.session_state.db


def _service() -> Any:
    cached = st.session_state.get("m020_galaxy")
    if cached is not None:
        return cached
    from ..galaxy import GalaxyService
    service = GalaxyService(_db())
    st.session_state.m020_galaxy = service
    return service


def render() -> None:
    st.header("🌌 Galaxy & Topics")
    st.caption(
        "A bounded 2D projection of a selected subcorpus with scalable clustering and "
        "interpretable topics. Coordinates are an exploratory projection — never literal "
        "semantic distance. Local-only; no raw PII is shown."
    )
    tabs = st.tabs(["Galaxy", "Clusters & topics", "Document context", "Topic over time"])
    with tabs[0]:
        _render_galaxy()
    with tabs[1]:
        _render_clusters()
    with tabs[2]:
        _render_context()
    with tabs[3]:
        _render_topic_time()


def _scope_controls(prefix: str) -> dict[str, Any]:
    c1, c2, c3 = st.columns(3)
    kind = c1.selectbox("Scope", SCOPE_OPTIONS, key=f"{prefix}_kind")
    scope: dict[str, Any] = {"kind": kind}
    if kind == "search":
        scope["query"] = c2.text_input("Query", key=f"{prefix}_q")
    elif kind == "category":
        scope["category"] = c2.text_input("Category", key=f"{prefix}_cat")
    elif kind == "language":
        scope["language"] = c2.text_input("Language (e.g. fr)", key=f"{prefix}_lang")
    elif kind == "entity":
        scope["entity_type"] = c2.text_input("Entity type", key=f"{prefix}_etype")
        scope["entity_value"] = c3.text_input("Entity value", key=f"{prefix}_evalue")
    elif kind == "date":
        scope["start"] = c2.text_input("Start (YYYY-MM-DD)", key=f"{prefix}_start")
        scope["end"] = c3.text_input("End (YYYY-MM-DD)", key=f"{prefix}_end")
        scope["source"] = c2.selectbox("Date source", ["modified_at", "created_at", "indexed_at"],
                                       key=f"{prefix}_dsource")
    elif kind == "dossier":
        scope["dossier_id"] = c2.text_input("Dossier id", key=f"{prefix}_dossier")
    elif kind == "prefix":
        scope["prefix"] = c2.text_input("Path prefix (local)", key=f"{prefix}_prefix")
    elif kind == "file_ids":
        raw = c2.text_input("Comma-separated file ids", key=f"{prefix}_ids")
        scope["ids"] = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    return scope


def _render_galaxy() -> None:
    service = _service()
    scope = _scope_controls("gal")
    c1, c2, c3, c4 = st.columns(4)
    method = c1.selectbox("Projection", METHOD_OPTIONS, key="gal_method")
    color_by = c2.selectbox("Color by", COLOR_OPTIONS, key="gal_color")
    k = c3.slider("Max clusters", 2, 48, 16, key="gal_k")
    aggregate = c4.selectbox("View", ["auto", "points", "clusters"], key="gal_agg")
    c5, c6, c7 = st.columns(3)
    collapse_dupes = c5.checkbox("Collapse exact duplicates", key="gal_dupes")
    collapse_versions = c6.checkbox("Collapse version families", key="gal_versions")
    limit = c7.number_input("Point limit", 100, 20000, 2000, step=100, key="gal_limit")
    if st.button("🌀 Build galaxy", type="primary", key="gal_build"):
        with st.spinner("Projecting and clustering…"):
            try:
                payload = service.galaxy(
                    scope=scope, method=method, limit=int(limit), color_by=color_by,
                    collapse_duplicates=collapse_dupes, collapse_versions=collapse_versions,
                    aggregate=(None if aggregate == "auto" else aggregate), k=int(k),
                    with_topics=True, persist=True)
            except Exception as exc:  # noqa: BLE001 - surface, never crash the app
                st.error(f"galaxy unavailable: {type(exc).__name__}: {exc}")
                return
        st.session_state.m020_payload = payload
    payload = st.session_state.get("m020_payload")
    if not payload:
        st.info("Choose a scope and build the galaxy.")
        return
    meta = payload.get("meta", {})
    cols = st.columns(4)
    cols[0].metric("Tier", str(payload.get("tier")))
    cols[1].metric("Points", f"{meta.get('returned_points', 0):,}")
    cols[2].metric("Input", f"{meta.get('input_count', 0):,}")
    cols[3].metric("Clusters", len(payload.get("clusters", [])))
    st.caption(" · ".join(meta.get("warnings", [])) or "")
    fig = _scatter(payload.get("points", []))
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.dataframe(payload.get("points", [])[:500], use_container_width=True)
    clusters = payload.get("clusters", [])
    if clusters:
        st.subheader("Cluster labels (evidence-backed)")
        st.dataframe(clusters, use_container_width=True)


def _scatter(points: list[dict[str, Any]]) -> Any:
    if not points:
        return None
    try:
        go = importlib.import_module("plotly.graph_objects")
    except Exception:  # noqa: BLE001
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    for point in points:
        key = str(point.get("color"))
        groups.setdefault(key, []).append(point)
    fig = go.Figure()
    for name, pts in sorted(groups.items()):
        fig.add_trace(go.Scatter(
            x=[p["x"] for p in pts], y=[p["y"] for p in pts], mode="markers",
            name=name, marker={"size": 7, "opacity": 0.75},
            text=[str(p.get("id")) for p in pts],
            hovertemplate="id=%{text}<extra>" + name + "</extra>"))
    fig.update_layout(height=560, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      xaxis={"visible": False}, yaxis={"visible": False},
                      title="Semantic galaxy (exploratory projection)")
    return fig


def _current_run() -> dict[str, Any] | None:
    payload = st.session_state.get("m020_payload") or {}
    run_id = payload.get("cluster_run_id")
    if run_id:
        return {"run_id": run_id}
    latest = _service().store.latest_cluster_run()
    return cast("dict[str, Any] | None", latest)


def _render_clusters() -> None:
    service = _service()
    run = _current_run()
    if not run:
        st.info("No cluster run yet. Build the galaxy or run 'pis clusters --build'.")
        return
    run_id = str(run["run_id"])
    status = service.store.run_status(run, current_freshness=service.current_freshness())
    st.caption(f"run {run_id} · {status['status']} · namespace {status.get('vector_namespace')}")
    if st.button("Compute / refresh topics", key="clu_topics"):
        with st.spinner("Extracting c-TF-IDF terms…"):
            try:
                service.build_topics(run_id, max_docs_per_cluster=80)
            except Exception as exc:  # noqa: BLE001
                st.error(f"topics unavailable: {type(exc).__name__}")
    topics = service.store.topics(run_id)
    if not topics:
        st.info("No topics persisted for this run yet.")
        return
    options = {f"[{t['cluster_id']}] {t['label']} ({t['size']})": t for t in topics}
    choice = st.selectbox("Cluster / topic", list(options), key="clu_choice")
    topic = cast(dict[str, Any], options[choice])
    _render_topic_detail(service, run_id, topic)


def _render_topic_detail(service: Any, run_id: str, topic: dict[str, Any]) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Size", topic.get("size", 0))
    c2.metric("Cohesion", f"{topic.get('cohesion'):.3f}" if topic.get("cohesion") else "—")
    c3.metric("Terms", len(topic.get("terms", [])))
    c4.metric("Reps", len(topic.get("representatives", [])))
    st.markdown("**Representative terms** (c-TF-IDF): " +
                ", ".join(t["term"] for t in topic.get("terms", [])[:12]))
    ent_col, cat_col = st.columns(2)
    with ent_col:
        st.markdown("**Entities**")
        st.dataframe(topic.get("entities", [])[:10], use_container_width=True)
    with cat_col:
        st.markdown("**Categories**")
        st.dataframe(topic.get("categories", [])[:10], use_container_width=True)
    st.markdown("**Representative documents**")
    st.dataframe(topic.get("representatives", []), use_container_width=True)
    evidence = topic.get("evidence", {})
    st.caption(f"label source: {evidence.get('label_source')} · method: {evidence.get('method')} "
               f"· llm_refined: {evidence.get('llm_refined')}")
    c1, c2, c3 = st.columns(3)
    if c1.button("➕ Create dossier from cluster", key="clu_dossier"):
        try:
            result = service.create_dossier_from_cluster(run_id, int(topic["cluster_id"]),
                                                         name=f"Cluster {topic['cluster_id']}")
            st.success(f"Dossier created with {result['member_count']} documents.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"dossier failed: {type(exc).__name__}")
    if c2.button("📄 Create report from cluster", key="clu_report"):
        try:
            result = service.report_from_cluster(run_id, int(topic["cluster_id"]),
                                                 title=topic.get("label") or "Cluster")
            st.success(f"Report definition created: {result['report_id']}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"report failed: {type(exc).__name__}")
    with c3:
        term = st.text_input("Search within cluster", key="clu_search")
        if term:
            detail = service.cluster_detail(run_id, int(topic["cluster_id"]), limit=200)
            member_ids = {int(m["file_id"]) for m in detail.get("members", [])}
            rows = [r for r in service.db.search_files(term, limit=100)
                    if int(r["id"]) in member_ids][:20]
            st.write(f"{len(rows)} match(es) inside the cluster")
            st.dataframe([{k: r.get(k) for k in ("id", "filename", "extension")} for r in rows],
                         use_container_width=True)


def _render_context() -> None:
    service = _service()
    file_id = st.number_input("Document id", min_value=1, value=1, step=1, key="ctx_id")
    if not st.button("Show context", key="ctx_btn"):
        return
    try:
        ctx = service.document_context(int(file_id))
    except Exception as exc:  # noqa: BLE001
        st.error(f"context unavailable: {type(exc).__name__}")
        return
    doc = ctx.get("document", {})
    cols = st.columns(4)
    cols[0].metric("Extension", doc.get("extension") or "—")
    cols[1].metric("Language", ctx["intel"].get("language") or "—")
    cols[2].metric("Sensitivity", ctx["intel"].get("max_severity") or "none")
    cols[3].metric("Dossiers", len(ctx.get("dossiers", [])))
    st.caption(f"file id {doc.get('id')} — raw PII is never displayed")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Semantic neighbours**")
        st.dataframe(ctx.get("semantic_neighbors", [])[:10], use_container_width=True)
        st.markdown("**Versions / duplicates**")
        st.json({"versions": ctx.get("versions"), "duplicates": ctx.get("duplicates", [])[:10]})
    with c2:
        st.markdown("**Entities**")
        st.dataframe(ctx["intel"].get("entities", [])[:15], use_container_width=True)
        st.markdown("**Cluster membership**")
        st.dataframe(ctx.get("cluster_membership", []), use_container_width=True)
    st.markdown("**Timeline neighbours**")
    st.dataframe(ctx.get("timeline_neighbors", []), use_container_width=True)


def _render_topic_time() -> None:
    service = _service()
    run = _current_run()
    if not run:
        st.info("Build or select a cluster run first.")
        return
    run_id = str(run["run_id"])
    c1, c2 = st.columns(2)
    group = c1.selectbox("Group by", GROUP_OPTIONS, index=2, key="tot_group")
    source = c2.selectbox("Date source", ["modified_at", "created_at", "indexed_at"],
                          key="tot_source")
    try:
        data = service.topic_over_time(run_id, group=group, source=source)
    except Exception as exc:  # noqa: BLE001
        st.error(f"topic-over-time unavailable: {type(exc).__name__}")
        return
    st.caption(f"date source: {data.get('date_source')} · confidence: {data.get('confidence')}")
    series = data.get("series", [])
    if not series:
        st.info("No dated members for this run.")
        return
    st.dataframe(series, use_container_width=True)
