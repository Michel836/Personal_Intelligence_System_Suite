"""Operations / System UI (M019).

Canonical app only. Aggregates health, doctor, maintenance, backup and API/vector
status. Destructive maintenance requires an explicit confirmation checkbox and
no source file is ever deleted.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st


def _db() -> Any:
    return st.session_state.db


def render() -> None:
    st.header("🧰 Operations & System")
    st.caption(
        "Local-only operations: health, diagnostics, maintenance, backup and the "
        "optional API/vector backends. No source file is ever modified or deleted."
    )
    tabs = st.tabs(["Health", "Doctor", "Maintenance", "Backup", "API & Vector"])
    with tabs[0]:
        _render_health()
    with tabs[1]:
        _render_doctor()
    with tabs[2]:
        _render_maintenance()
    with tabs[3]:
        _render_backup()
    with tabs[4]:
        _render_api_vector()


def _render_health() -> None:
    from ..ops.health import health_report
    try:
        report = health_report(_db(), include_paths=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"health unavailable: {type(exc).__name__}")
        return
    cols = st.columns(4)
    cols[0].metric("Status", report["status"])
    cols[1].metric("Files", f"{report['db'].get('files_total') or 0:,}")
    cols[2].metric("Queue", report["ingestion_queue"].get("total", 0))
    cols[3].metric("Schema", report["schema"].get("fts_schema_version") or "?")
    st.json({"db": report["db"], "semantic": report["semantic"],
             "privacy_policy": report["privacy_policy"], "api_bind": report["api_bind"],
             "vector_backend": report["vector_backend"]})


def _render_doctor() -> None:
    from ..ops.doctor import run_doctor
    include_paths = st.checkbox("Include local paths", value=False, key="m019_doctor_paths")
    if st.button("Run doctor", key="m019_doctor_run"):
        try:
            report = run_doctor(_db(), include_paths=include_paths, probe_network=False)
            st.session_state["m019_doctor"] = report
        except Exception as exc:  # noqa: BLE001
            st.error(f"doctor failed: {type(exc).__name__}")
            return
    cached = st.session_state.get("m019_doctor")
    if not cached:
        st.info("Run the doctor to see diagnostics.")
        return
    st.metric("Overall", cached["status"])
    st.dataframe([{"check": c["name"], "status": c["status"], "detail": c["detail"]}
                  for c in cached["checks"]], use_container_width=True)
    deps = cached.get("dependencies", {})
    st.caption(f"tools missing: {', '.join(deps.get('tools_missing', [])) or 'none'}")


def _render_maintenance() -> None:
    from ..ops.maintenance import MaintenanceService
    service = MaintenanceService(_db())
    ops = [o for o in service.operations() if o != "list"]
    op = st.selectbox("Operation", ops, key="m019_maint_op")
    st.caption({
        "integrity": "PRAGMA integrity_check (full scan; can be slow on large DBs)",
        "analyze": "refresh query-planner statistics",
        "optimize": "PRAGMA optimize (routine, safe)",
        "checkpoint": "WAL checkpoint (TRUNCATE)",
        "vacuum": "rebuild the DB file; requires confirmation + free space",
        "fts-rebuild": "rebuild the FTS index and verify row counts",
    }.get(op, "bounded maintenance operation"))
    if op == "vacuum":
        precheck = service.vacuum_precheck()
        st.warning(f"VACUUM needs ~{precheck['needed_bytes']:,} bytes free "
                   f"(available {precheck['free_bytes']:,}).")
        confirm = st.checkbox("I understand VACUUM rewrites the database", key="m019_vacuum_confirm")
    else:
        confirm = False
    if st.button("Run", key="m019_maint_run"):
        kwargs = {"confirm": confirm} if op == "vacuum" else {}
        try:
            result = service.run(op, **kwargs)
            st.session_state["m019_maint_result"] = result
        except Exception as exc:  # noqa: BLE001
            st.error(f"maintenance failed: {type(exc).__name__}")
    cached = st.session_state.get("m019_maint_result")
    if cached:
        st.success(f"{cached['op']}: {cached['status']} ({cached['duration_s']}s)")
        st.json(cached.get("details", {}))


def _render_backup() -> None:
    from ..ops.backup import create_backup, verify_backup
    from ..ops.config import effective_config
    cfg = effective_config(include_paths=True)
    st.caption(f"Backup directory: {cfg['paths']['backup_dir']}")
    st.caption("Source corpus is never included. Config is secret-redacted.")
    if st.button("Create backup", key="m019_backup_run"):
        try:
            result = create_backup(_db())
            st.session_state["m019_backup_result"] = result.as_dict()
        except Exception as exc:  # noqa: BLE001
            st.error(f"backup failed: {type(exc).__name__}")
    cached = st.session_state.get("m019_backup_result")
    if cached:
        st.success(f"Backup {cached['backup_id']} -> {cached['archive_path']}")
        st.json(cached["manifest"])
    st.divider()
    st.markdown("**Validate a backup (no restore)**")
    archive = st.text_input("Backup archive path", key="m019_backup_verify_path")
    if archive and st.button("Verify", key="m019_backup_verify"):
        report = verify_backup(Path(archive))
        if report.get("ok"):
            st.success("Backup is valid.")
        else:
            st.error(f"Invalid backup: {report.get('error') or report.get('problems')}")
        st.json(report.get("manifest", {}).get("components", {}))


def _render_api_vector() -> None:
    from ..api import bind_warning
    from ..ops.config import effective_config
    from ..ops.instance import detect_instances
    from ..ops.pgvector import (
        benchmark,
        decide,
        pgvector_available,
        resolve_vector_backend,
    )
    cfg = effective_config(include_paths=False)
    st.markdown("**Local API**")
    st.json({"host": cfg["api_host"], "port": cfg["api_port"],
             "loopback_only": cfg["api_host"] in ("127.0.0.1", "::1", "localhost")})
    warning = bind_warning(cfg["api_host"])
    if warning:
        st.error(warning)
    st.caption("Disable with an unset host/port or by not running the server. "
               "Run it with `pis api`.")
    st.markdown("**Vector backend**")
    st.json(resolve_vector_backend())
    if st.button("Probe PostgreSQL/pgvector", key="m019_pg_probe"):
        st.json({"available": pgvector_available(), "decision": decide(benchmark_result=benchmark())})
    st.markdown("**App instances**")
    instances = detect_instances()
    if instances:
        st.dataframe(instances, use_container_width=True)
    else:
        st.caption("No duplicate Streamlit instances detected.")
