"""Production-safe Streamlit scanner page.

This page intentionally exposes only controls that the canonical scanner can
honestly honour.  It does not materialise a full scan in RAM, never reconciles a
bounded/post-filtered subset, and does not advertise unsupported pause/thread
controls.
"""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

import streamlit as st

from src.ui.scanner_runtime import run_scan_paths
from src.utils.disk_utils import (
    get_available_drives,
    get_recommended_drives,
    validate_scan_path,
)


def _fmt_bytes(value: int) -> str:
    size = float(value or 0)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _ensure_state() -> None:
    defaults: dict[str, Any] = {
        "safe_scan_thread": None,
        "safe_scan_cancel_event": None,
        "safe_scan_queue": None,
        "safe_scan_status": "idle",
        "safe_scan_update": {},
        "safe_scan_history": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _drain_updates() -> None:
    q = st.session_state.safe_scan_queue
    if q is None:
        return
    while True:
        try:
            update = q.get_nowait()
        except queue.Empty:
            break
        st.session_state.safe_scan_update = update
        status = str(update.get("status", "running"))
        st.session_state.safe_scan_status = status
        if status in {"completed", "failed", "cancelled"}:
            st.session_state.safe_scan_history.append(update)


def _worker(db: Any, paths: list[str], cancel_event: threading.Event, q: queue.Queue) -> None:
    def emit(update: dict[str, Any]) -> None:
        q.put(update)

    try:
        results = run_scan_paths(
            db,
            paths,
            cancel_event=cancel_event,
            update=emit,
            batch_size=1000,
        )
        if not results and cancel_event.is_set():
            emit({"status": "cancelled", "message": "Cancelled before traversal"})
    except Exception as exc:  # defensive UI boundary; ScanService already fails closed
        emit(
            {
                "status": "failed",
                "message": f"{type(exc).__name__}: {exc}",
                "error": str(exc),
            }
        )


def _render_volume_overview(drives: list[dict[str, Any]]) -> None:
    st.markdown("### 💽 Volumes de stockage détectés")
    total = sum(int(d.get("total_space", 0) or 0) for d in drives)
    free = sum(int(d.get("free_space", 0) or 0) for d in drives)
    col1, col2, col3 = st.columns(3)
    col1.metric("Volumes", len(drives))
    col2.metric("Capacité montée", _fmt_bytes(total))
    col3.metric("Libre", _fmt_bytes(free))

    if not drives:
        st.error("Aucun volume de stockage utilisateur détecté.")
        return

    for drive in drives:
        st.caption(
            f"{drive.get('path')} · {drive.get('device', '')} · "
            f"{drive.get('type', 'unknown')} · "
            f"{_fmt_bytes(int(drive.get('total_space', 0) or 0))}"
        )


def _selected_paths(drives: list[dict[str, Any]]) -> list[str]:
    recommended = set(get_recommended_drives())
    options = [str(d["path"]) for d in drives]
    defaults = [p for p in options if p in recommended]

    selected = st.multiselect(
        "Volumes à scanner intégralement",
        options,
        default=defaults,
        help=(
            "Un scan de production parcourt intégralement chaque racine choisie. "
            "La réconciliation n'a lieu qu'après une traversée complète et sans erreur."
        ),
    )

    custom = st.text_area(
        "Chemins supplémentaires (un par ligne, optionnel)",
        placeholder="/home/chu/Documents\n/mnt/archive",
        height=90,
    )
    if custom.strip():
        for raw in custom.splitlines():
            path = raw.strip()
            if not path:
                continue
            validation = validate_scan_path(path)
            if validation.get("valid"):
                selected.append(str(Path(path).expanduser().resolve()))
            else:
                errors = "; ".join(validation.get("errors") or ["chemin invalide"])
                st.error(f"{path}: {errors}")

    # Stable de-duplication while preserving UI order.
    return list(dict.fromkeys(selected))


def _render_progress() -> None:
    update = st.session_state.safe_scan_update or {}
    status = st.session_state.safe_scan_status

    st.markdown("### 🎛️ État du scan")
    if status == "idle":
        st.info("Prêt. Aucun scan en cours.")
        return

    path = update.get("path", "")
    seen = int(update.get("files_seen", 0) or 0)
    upserted = int(update.get("files_upserted", 0) or 0)
    errors = int(update.get("files_errors", 0) or 0)
    fps = float(update.get("files_per_second", 0.0) or 0.0)
    elapsed = float(update.get("elapsed_s", 0.0) or 0.0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("État", status.upper())
    col2.metric("Fichiers vus", f"{seen:,}")
    col3.metric("Écrits / actualisés", f"{upserted:,}")
    col4.metric("Erreurs", f"{errors:,}")
    st.caption(f"Racine: {path or '—'} · {fps:,.1f} fichiers/s · {elapsed:,.1f}s")

    if status == "running":
        st.info(
            "Scan en cours. Le nombre total n'est pas inventé : la progression est "
            "affichée en compteurs réels jusqu'à la fin de la traversée."
        )
    elif status == "completed":
        st.success(
            f"Scan terminé et réconcilié. Renommés: {int(update.get('renamed', 0) or 0):,} · "
            f"Manquants: {int(update.get('missing', 0) or 0):,}."
        )
    elif status == "cancelled":
        st.warning("Scan annulé. Aucune réconciliation destructive n'a été effectuée.")
    elif status == "failed":
        st.error(
            "Scan échoué en mode fail-closed. Aucune réconciliation destructive n'a été effectuée. "
            f"{update.get('message', '')}"
        )


def scanner_page() -> None:
    """Render the canonical, production-safe scanner UI."""
    _ensure_state()
    _drain_updates()

    st.header("🚀 Scanner")
    st.caption(
        "Scanner de production PISS · streaming borné · lifecycle canonique · "
        "réconciliation uniquement après parcours complet"
    )

    drives = get_available_drives()
    _render_volume_overview(drives)
    paths = _selected_paths(drives)

    st.markdown("### ⚙️ Politique de scan")
    st.info(
        "Les limites artificielles de fichiers, le filtre de taille post-scan, le faux sélecteur "
        "de threads et Pause/Resume ont été retirés. Ils pouvaient rendre l'index incohérent ou "
        "afficher un état différent de la réalité."
    )
    st.write(f"**Racines sélectionnées :** {len(paths)}")
    for path in paths:
        st.caption(f"• {path}")

    thread = st.session_state.safe_scan_thread
    running = bool(thread is not None and thread.is_alive())

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        if st.button(
            "🚀 Lancer le scan complet",
            type="primary",
            use_container_width=True,
            disabled=running or not paths,
        ):
            q: queue.Queue = queue.Queue()
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=_worker,
                args=(st.session_state.db, paths, cancel_event, q),
                name="pis-ui-scan",
                daemon=True,
            )
            st.session_state.safe_scan_queue = q
            st.session_state.safe_scan_cancel_event = cancel_event
            st.session_state.safe_scan_thread = worker
            st.session_state.safe_scan_status = "running"
            st.session_state.safe_scan_update = {
                "status": "running",
                "path": paths[0],
                "files_seen": 0,
                "files_upserted": 0,
                "files_errors": 0,
                "message": "Starting",
            }
            worker.start()
            st.rerun()

    with col2:
        if st.button("⏹️ Arrêter", use_container_width=True, disabled=not running):
            event = st.session_state.safe_scan_cancel_event
            if event is not None:
                event.set()
            st.info("Demande d'arrêt envoyée. La réconciliation sera annulée.")

    with col3:
        if st.button("🔄 Actualiser", use_container_width=True):
            st.rerun()

    with col4:
        if st.button("📊 Statistiques", use_container_width=True, disabled=running):
            st.session_state.redirect_to_stats = True
            st.rerun()

    _drain_updates()
    _render_progress()

    if st.session_state.safe_scan_history:
        with st.expander("Historique de cette session"):
            for item in st.session_state.safe_scan_history[-10:]:
                st.json(item)
