"""Dossiers & Reports UI (M018).

Canonical app only. Bounded, local-only, no destructive source action. The page
drives the same services as the CLI/bench, so nothing is duplicated here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from ..reports.dossiers import DossierService
from ..reports.models import DossierMode, ReportKind
from ..reports.pdf_export import available_providers
from ..reports.privacy import PRIVACY_MODES, describe_mode


def _db() -> Any:
    return st.session_state.db


def _dossiers() -> DossierService:
    cached = st.session_state.get("m018_dossiers")
    if isinstance(cached, DossierService):
        return cached
    service = DossierService(_db())
    st.session_state.m018_dossiers = service
    return service


def _export() -> Any:
    if "m018_export" not in st.session_state:
        from ..reports.export import ExportService
        st.session_state.m018_export = ExportService(_db())
    return st.session_state.m018_export


def add_to_dossier_widget(db: Any, file_ids: list[int], *, key_prefix: str = "add") -> None:
    """Reusable 'Add to dossier' control for document/search/graph pages."""
    if not file_ids:
        st.caption("Select at least one document to add it to a dossier.")
        return
    service = DossierService(db)
    dossiers = service.list_dossiers()
    options = ["(new dossier)"] + [f"{d['name']} ({d['member_count']})" for d in dossiers]
    choice = st.selectbox("Add to dossier", options, key=f"{key_prefix}_sel")
    name = st.text_input("New dossier name", key=f"{key_prefix}_name") if choice == "(new dossier)" else ""
    if st.button("➕ Add to dossier", key=f"{key_prefix}_btn"):
        try:
            if choice == "(new dossier)":
                if not name.strip():
                    st.warning("Enter a dossier name.")
                    return
                dossier = service.create(name.strip(), file_ids=file_ids)
                st.success(f"Created dossier {dossier.get('name')!r} with {len(file_ids)} document(s).")
            else:
                did = dossiers[options.index(choice) - 1]["dossier_id"]
                added = service.add_documents(did, file_ids)
                st.success(f"Added {added} document(s) to the dossier.")
        except Exception as exc:  # noqa: BLE001 - UI must never crash
            st.error(f"Could not add to dossier: {type(exc).__name__}")


def render() -> None:
    st.header("📁 Dossiers & Reports")
    st.caption(
        "Assemble indexed intelligence into reproducible reports and evidence packs. "
        "Local-only; sources are never modified and nothing is sent remotely unless "
        "you explicitly allowed it."
    )
    tabs = st.tabs(["My dossiers", "Create dossier", "Build report", "Export", "History"])
    with tabs[0]:
        _render_dossiers()
    with tabs[1]:
        _render_create_dossier()
    with tabs[2]:
        _render_build()
    with tabs[3]:
        _render_export()
    with tabs[4]:
        _render_history()


# --- dossiers ---------------------------------------------------------------
def _render_dossiers() -> None:
    service = _dossiers()
    dossiers = service.list_dossiers()
    if not dossiers:
        st.info("No dossiers yet. Create one from the 'Create dossier' tab or from a selection.")
        return
    labels = [f"{d['name']} · {d['mode']} · {d['member_count']} docs" for d in dossiers]
    idx = st.selectbox("Dossier", range(len(labels)), format_func=lambda i: labels[i], key="m018_dos_pick")
    dossier = dossiers[idx]
    did = dossier["dossier_id"]
    resolved = service.resolve(did)
    c1, c2, c3 = st.columns(3)
    c1.metric("Members", resolved.get("count", 0))
    c2.metric("Missing", resolved.get("missing", 0))
    c3.metric("Mode", resolved.get("mode", "?"))
    if resolved.get("frozen"):
        st.caption(f"Snapshot taken {resolved['frozen'].get('at')}")
    if resolved.get("members"):
        st.dataframe([
            {"file_id": m["file_id"], "name": m.get("filename"), "state": m.get("state"),
             "source": m.get("source"), "section": m.get("section")}
            for m in resolved["members"]], use_container_width=True)
    with st.expander("Manage membership"):
        remove_ids = st.multiselect("Remove file ids", [m["file_id"] for m in resolved["members"]],
                                    key="m018_dos_remove")
        note_id = st.number_input("Note for file id", min_value=0, step=1, value=0, key="m018_dos_note_id")
        note_text = st.text_input("Note", key="m018_dos_note_text")
        b1, b2, b3 = st.columns(3)
        if b1.button("Remove", key="m018_dos_remove_btn") and remove_ids:
            service.remove_documents(did, remove_ids)
            st.rerun()
        if b2.button("Save note", key="m018_dos_note_btn") and note_id and note_text:
            service.set_note(did, int(note_id), note_text)
            st.success("Note saved.")
        if b3.button("Freeze snapshot", key="m018_dos_freeze_btn"):
            service.freeze(did)
            st.success("Snapshot frozen.")
    diff = service.compare_snapshot(did)
    if diff.get("has_snapshot"):
        st.markdown("**Snapshot vs current**")
        st.write({"added": diff.get("added"), "removed": diff.get("removed"),
                  "unchanged": diff.get("unchanged"), "snapshot_at": diff.get("snapshot_at")})
    if st.button("📄 Build dossier report", key="m018_dos_report"):
        st.session_state["m018_build_kind"] = ReportKind.DOSSIER.value
        st.session_state["m018_build_dossier"] = did
        st.success("Dossier selected in the 'Build report' tab.")


def _render_create_dossier() -> None:
    service = _dossiers()
    with st.form("m018_create_dos"):
        name = st.text_input("Name")
        description = st.text_input("Description")
        mode = st.selectbox("Mode", [DossierMode.STATIC.value, DossierMode.DYNAMIC.value])
        query = st.text_input("Saved query (dynamic)")
        extension = st.text_input("Extension filter (e.g. .pdf)")
        category = st.text_input("Category filter")
        entity_type = st.text_input("Entity type")
        entity_value = st.text_input("Entity value")
        limit = st.number_input("Limit", min_value=1, value=200, step=50)
        manual = st.text_input("Manual file ids (comma-separated)")
        submitted = st.form_submit_button("Create dossier")
    if submitted:
        if not name.strip():
            st.warning("Name is required.")
            return
        q = {k: v for k, v in {
            "query": query, "extension": extension, "category": category,
            "entity_type": entity_type, "entity_value": entity_value, "limit": int(limit),
        }.items() if v}
        fids = [int(x) for x in manual.replace(" ", "").split(",") if x.strip().isdigit()]
        dossier = service.create(name.strip(), description=description, mode=mode,
                                 query=q, file_ids=fids)
        st.success(f"Created dossier {dossier.get('name')!r}.")
        if mode == DossierMode.DYNAMIC.value:
            resolved = service.resolve(dossier["dossier_id"])
            st.info(f"Dynamic dossier currently matches {resolved.get('count', 0)} document(s).")


# --- build report -----------------------------------------------------------
def _render_build() -> None:
    export = _export()
    kinds = [k.value for k in ReportKind]
    default_kind = st.session_state.get("m018_build_kind", ReportKind.SEARCH.value)
    kind = st.selectbox("Report type", kinds, index=kinds.index(default_kind) if default_kind in kinds else 0)
    title = st.text_input("Title")
    description = st.text_input("Description")
    mode = st.selectbox("Privacy mode", PRIVACY_MODES,
                        format_func=lambda m: describe_mode(m)["label"])
    st.caption(describe_mode(mode)["banner"])
    query = st.text_input("Query")
    manual = st.text_input("Document ids (comma-separated)")
    excerpts = st.checkbox("Include bounded content excerpts", value=True)
    summarize = st.checkbox("Generate optional AI summary", value=False)
    dossier_id = st.session_state.get("m018_build_dossier") if kind == ReportKind.DOSSIER.value else None
    if kind == ReportKind.DOSSIER.value:
        dossier_id = st.text_input("Dossier id", value=dossier_id or "")
    if st.button("👁️ Build preview", key="m018_build_preview"):
        try:
            definition = export.create_definition(
                kind, title or f"Untitled {kind}", description=description,
                privacy_mode=mode, query={"query": query} if query else {},
                document_ids=[int(x) for x in manual.replace(" ", "").split(",") if x.strip().isdigit()],
                options={"excerpts": excerpts, "dossier_id": dossier_id} if dossier_id
                else {"excerpts": excerpts})
            ir = export.builder.build(definition)
            st.session_state["m018_preview_ir"] = ir
            st.session_state["m018_preview_def"] = definition
            st.session_state["m018_build_summarize"] = bool(summarize)
            st.success(f"Built {len(ir.sections)} section(s), {len(ir.sources)} source(s).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Build failed: {type(exc).__name__}: {exc}")
    ir = st.session_state.get("m018_preview_ir")
    if ir is not None:
        from ..reports.html_export import render_html
        st.download_button("⬇️ Download preview HTML", render_html(ir).encode("utf-8"),
                           file_name="report-preview.html", mime="text/html")
        with st.expander("HTML preview", expanded=True):
            st.components.v1.html(render_html(ir), height=500, scrolling=True)
        st.json(ir.as_dict())


# --- export -----------------------------------------------------------------
def _render_export() -> None:
    export = _export()
    definition = st.session_state.get("m018_preview_def")
    if definition is None:
        st.info("Build a report in the 'Build report' tab first.")
        return
    formats = st.multiselect("Formats", ["HTML", "PDF", "JSON"], default=["HTML", "JSON"])
    summarize = st.session_state.get("m018_build_summarize", False)
    if summarize:
        st.caption("Optional AI summary will be attached (grounded in the report sources only).")
    overwrite = st.checkbox("Allow overwriting / regenerating", value=False)
    providers = available_providers()
    st.caption("PDF providers: " + ", ".join(
        f"{name}={'yes' if info['available'] else 'no'}" for name, info in providers.items()))
    if st.button("📦 Export", key="m018_export_btn"):
        try:
            result = export.generate(definition, formats=tuple(formats), summarize=summarize,
                                     overwrite=overwrite)
            st.session_state["m018_last_export"] = result
            st.success(f"Exported {len(result.artifacts)} artifact(s).")
            for warning in result.warnings:
                st.warning(warning)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Export failed: {type(exc).__name__}: {exc}")
    result = st.session_state.get("m018_last_export")
    if result is not None:
        for artifact in result.artifacts:
            path = Path(artifact.path)
            if path.is_file():
                mime = {"HTML": "text/html", "PDF": "application/pdf",
                        "JSON": "application/json"}.get(artifact.format, "application/octet-stream")
                st.download_button(
                    f"⬇️ {artifact.format} · {path.name} ({artifact.size_bytes:,} B)",
                    path.read_bytes(), file_name=path.name, mime=mime,
                    key=f"m018_dl_{path.name}")
        if result.manifest_path:
            st.caption(f"Manifest: {result.manifest_path}")


# --- history ----------------------------------------------------------------
def _render_history() -> None:
    export = _export()
    store = export.store
    definitions = store.list_definitions(limit=100)
    st.markdown("**Report definitions**")
    if definitions:
        st.dataframe([{"report_id": d["report_id"], "kind": d["kind"], "title": d["title"],
                       "privacy": d["privacy_mode"], "updated": d.get("updated_at") or d["created_at"]}
                      for d in definitions], use_container_width=True)
        pick = st.selectbox("Regenerate", [d["report_id"] for d in definitions], key="m018_regen_pick")
        if st.button("♻️ Regenerate", key="m018_regen_btn"):
            result = export.regenerate(pick)
            if result is None:
                st.warning("Definition not found.")
            else:
                st.success(f"Regenerated {len(result.artifacts)} artifact(s).")
    else:
        st.caption("No report definitions yet.")
    st.markdown("**Artifacts**")
    artifacts = store.list_artifacts(limit=200)
    if artifacts:
        st.dataframe([{"report_id": a["report_id"], "format": a["format"],
                       "file": Path(a["path"]).name if a.get("path") else None,
                       "exists": a.get("exists"), "bytes": a.get("size_bytes"),
                       "generated": a.get("generated_at"), "privacy": a.get("privacy_mode")}
                      for a in artifacts], use_container_width=True)
    else:
        st.caption("No artifacts generated yet.")
