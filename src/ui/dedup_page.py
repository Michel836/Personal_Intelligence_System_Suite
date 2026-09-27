"""Canonical UI surface for duplicates, versions, related docs and reranking.

Suggestions only: no destructive action (no delete/merge/rename/move) is ever
offered here. Heavy operations run behind explicit buttons.
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from ..core.launch_profile import Capability, has_capability


def _db():
    return st.session_state.db


def _store():
    from ..dedup import DedupStore

    if "dedup_store" not in st.session_state:
        st.session_state.dedup_store = DedupStore(_db())
    return st.session_state.dedup_store


def _semantic_available() -> bool:
    return has_capability(Capability.SEMANTIC_SEARCH) and bool(os.environ.get("PIS_EMBEDDING_STORE_DIR"))


def _embed_store():
    from ..intelligence.embedding_store import EmbeddingMatrixStore

    if "dedup_embed_store" not in st.session_state:
        base = os.environ.get("PIS_EMBEDDING_STORE_DIR")
        if not base:
            return None
        estore = EmbeddingMatrixStore("bge-m3", "BAAI/bge-m3", 1024, base_dir=Path(base))
        if not estore.load():
            return None
        st.session_state.dedup_embed_store = estore
    return st.session_state.dedup_embed_store


def render() -> None:
    st.header("🧬 Duplicates, Versions & Related")
    st.caption(
        "Evidence-based suggestions only — nothing is deleted, merged, renamed or moved. "
        "Exact duplicates use content SHA-256; near duplicates use embeddings + explainable scores."
    )
    db = _db()
    store = _store()
    stats = store.hash_stats()
    cols = st.columns(4)
    cols[0].metric("Active files", f"{stats['active_files']:,}")
    cols[1].metric("Hash coverage", f"{stats['coverage']*100:.1f}%")
    cols[2].metric("Exact groups", f"{len(store.exact_duplicate_groups(max_groups=1000)):,}")
    cols[3].metric("Version families", f"{store.version_family_stats()['families']:,}")

    tab_exact, tab_near, tab_versions, tab_related, tab_search = st.tabs(
        ["Exact duplicates", "Near duplicates", "Versions", "Related", "Reranked search"]
    )
    with tab_exact:
        _render_exact(db, store)
    with tab_near:
        _render_near(db, store)
    with tab_versions:
        _render_versions(db, store)
    with tab_related:
        _render_related(db, store)
    with tab_search:
        _render_search(db, store)


def _render_exact(db, store) -> None:
    from ..dedup import ExactDuplicateEngine

    st.subheader("Exact duplicates (identical bytes)")
    c1, c2, c3 = st.columns(3)
    min_size = c1.number_input("Minimum size (bytes)", min_value=1, value=1024, step=1024)
    max_mb = c2.number_input("Max size to hash (MB)", min_value=1, value=50, step=10)
    include_members = c3.checkbox("Include archive members", value=False)
    if st.button("Compute content hashes for duplicate candidates", key="m014_hash"):
        engine = ExactDuplicateEngine(db, store)
        with st.spinner("Hashing shared-size candidates..."):
            res = engine.hash_duplicate_candidates(min_size=int(min_size),
                                                   max_size=int(max_mb) * 1024 * 1024,
                                                   include_members=include_members)
        st.success(f"Hashed {res['hashed']:,} candidates ({res['ok']:,} ok, "
                   f"{res['bytes_hashed']/1e9:.2f} GB read).")
    groups = store.exact_duplicate_groups(min_size=int(min_size), include_members=include_members,
                                          max_groups=200)
    if not groups:
        st.info("No exact duplicate groups at this threshold (or hashes not computed yet).")
        return
    st.write(f"**{len(groups)} groups** · "
             f"{sum(g['count']-1 for g in groups):,} redundant copies · "
             f"{sum(g['wasted_bytes'] for g in groups)/1e9:.2f} GB reclaimable (informational).")
    for g in groups[:50]:
        with st.expander(f"{g['count']} copies · {g['size_bytes']/1024:.0f} KB each · "
                         f"{g['wasted_bytes']/1e6:.1f} MB reclaimable"):
            if g.get("members_truncated"):
                st.caption(f"Showing {len(g['members'])} of {g['count']} copies.")
            for m in g["members"]:
                tag = "archive" if m["document_kind"] == "ARCHIVE_MEMBER" else "file"
                st.text(f"[{m['id']}] ({tag}, {m['state']}) {m['path']}")


def _render_near(db, store) -> None:
    from ..dedup import NearDuplicateEngine

    st.subheader("Near duplicates (high semantic similarity, not byte-identical)")
    if not _semantic_available():
        st.info("Near-duplicate discovery needs the semantic capability and an embedding store "
                "(SMART/FULL profile with PIS_EMBEDDING_STORE_DIR).")
        return
    c1, c2 = st.columns(2)
    threshold = c1.slider("Similarity threshold", 0.70, 0.99, 0.90, 0.01)
    max_docs = c2.number_input("Max documents", min_value=1000, value=80000, step=5000)
    if st.button("Build near-duplicate relations", key="m014_near"):
        estore = _embed_store()
        engine = NearDuplicateEngine(db, store, embed_store=estore)
        with st.spinner("Generating bounded candidates (LSH) and confirming..."):
            res = engine.build(threshold=float(threshold), max_docs=int(max_docs))
        st.success(f"{res['near_duplicate_edges']:,} near-duplicate edges "
                   f"from {res['candidate_pairs']:,} candidates ({res['candidate_source']}).")
    n = store.near_duplicate_stats()["edges"]
    st.write(f"Stored near-duplicate edges: **{n:,}**")


def _render_versions(db, store) -> None:
    from ..dedup import VersionTracker

    st.subheader("Version families (explicit-marker confidence)")
    if st.button("Rebuild version families", key="m014_versions"):
        tracker = VersionTracker(db, store)
        with st.spinner("Grouping versions..."):
            res = tracker.build()
        st.success(f"{res['families']:,} families ({res['by_confidence']}).")
    families = store.version_families(limit=200)
    if not families:
        st.info("No version families yet.")
        return
    for fam in families[:50]:
        st.markdown(f"**{fam['base_name'] or '(family)'}** · confidence `{fam['confidence']}` · "
                    f"{fam['member_count']} members")
        members = _family_members(store, fam["id"])
        for m in members:
            order = "newest" if m.get("is_primary") else f"rank {m.get('rank')}"
            st.text(f"  [{m['id']}] {order} · {m['state']} · {m['path']}")


def _family_members(store, family_id: int):
    with store.db.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT vm.file_id AS id, vm.rank, vm.is_primary, f.path, f.state "
            "FROM version_members vm JOIN files f ON f.id=vm.file_id "
            "WHERE vm.family_id=? ORDER BY vm.rank ASC", (family_id,)).fetchall()]


def _render_related(db, store) -> None:
    from ..dedup.related import RelatedDocuments

    st.subheader("Related documents")
    if not _semantic_available():
        st.info("Related documents need an embedding store (SMART/FULL profile).")
        return
    file_id = st.number_input("Document id", min_value=1, value=1, step=1)
    limit = st.slider("Results", 5, 50, 10)
    include_missing = st.checkbox("Include missing documents", value=False)
    if st.button("Find related", key="m014_related"):
        estore = _embed_store()
        rel = RelatedDocuments(db, dedup_store=store, embed_store=estore)
        results = rel.related(int(file_id), limit=int(limit), include_missing=include_missing)
        if not results:
            st.info("No related suggestions (document may not be embedded).")
        for r in results:
            st.text(f"[{r['id']}] {r.get('semantic_similarity')} · {r['reason']} · {r['path']}")


def _render_search(db, store) -> None:
    from ..dedup.rerank import rerank_search

    st.subheader("Reranked search (lexical + semantic fusion)")
    query = st.text_input("Query", key="m014_query")
    c1, c2, c3 = st.columns(3)
    collapse = c1.checkbox("Collapse exact duplicates", value=True)
    diversity = c2.checkbox("Version diversity", value=False)
    show_all = c3.checkbox("Show all copies/versions", value=False)
    if query and st.button("Rerank", key="m014_rerank"):
        engine = None
        if _semantic_available():
            try:
                from ..intelligence.semantic_search import SemanticSearchEngine
                engine = SemanticSearchEngine(db)
            except Exception:
                engine = None
        results = rerank_search(db, engine, query, limit=20, dedup_store=store,
                                collapse_duplicates=collapse, version_diversity=diversity,
                                show_all_copies=show_all, show_all_versions=show_all)
        if not results:
            st.info("No results.")
        for r in results:
            badge = "exact" if r.get("exact_title_boost") else r.get("search_type", "lexical")
            st.text(f"[{r['id']}] {badge} · fusion={r.get('fusion_score')} · {r.get('path')}")
