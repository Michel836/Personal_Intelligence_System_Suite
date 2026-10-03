"""Four-screen Lite experience within the canonical application."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.core.database import DatabaseManager, default_db_path
from src.core.lite_workflow import LiteJob, validate_root

PAGES = ("🚀 Scanner", "🔄 Extraire", "🔍 Search", "🧰 État du système")


@st.cache_resource
def _resources(db_path: str):
    """One worker per database/process, shared across tabs and reruns."""
    db = DatabaseManager(Path(db_path))
    # Startup only: a second tab reuses this resource, never recovers a live job.
    db.recover_stale_runs()
    return db, LiteJob(db.db_path)


def _progress(job: LiteJob) -> None:
    state = job.snapshot()
    status = state["status"]
    if status == "IDLE":
        return
    labels = {"RUNNING": "En cours", "COMPLETED": "Terminé", "CANCELLED": "Arrêté", "FAILED": "Échec"}
    st.write(f"**{labels.get(status, status)}** · {state.get('processed', 0)} fichiers traités")
    if state.get("counts"):
        st.write(state["counts"])
    if state.get("error"):
        st.error(state["error"])
    if status == "CANCELLED":
        st.info("Les fichiers déjà traités sont conservés. Relancez l’opération pour continuer.")
    if job.running:
        if st.button("Arrêter", key="lite_cancel"):
            job.cancel()
            st.info("Arrêt demandé ; le fichier en cours peut encore terminer son traitement.")
    st.button("Actualiser", key="lite_refresh")


def render() -> None:
    db, job = _resources(str(Path(default_db_path()).resolve()))
    st.session_state.lite_db = db
    st.session_state.lite_job = job
    st.title("🔍 PISS Lite")
    st.caption("Indexer → Extraire → Rechercher → Consulter")
    with st.sidebar:
        st.caption(f"Base : {db.db_path.resolve()}")
        st.caption("Traitement local · aucun modèle IA nécessaire")
        page = st.radio("Navigation", PAGES)
    # Fragment refreshes progress without rerunning an operation or the whole app.
    if hasattr(st, "fragment"):
        st.fragment(run_every="1s" if job.running else None)(_progress)(job)
    else:
        _progress(job)
    if page == PAGES[0]:
        st.header("Indexer un dossier")
        root = st.text_input("Dossier à indexer", key="lite_root",
                             placeholder="/home/chu/Documents")
        st.info("Commencez par un petit dossier. Le scan indexe les noms et emplacements ; l’extraction rend le contenu recherchable.")
        if st.button("Lancer le scan", type="primary", disabled=job.running):
            try:
                validated = validate_root(root)
                job.start("scan", str(validated))
                st.session_state.lite_scope = str(validated)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        st.caption("Les fichiers sources restent inchangés. Les dossiers techniques et certains fichiers système sont exclus par le scanner.")
    elif page == PAGES[1]:
        st.header("Extraire le contenu")
        scope = st.session_state.get("lite_scope")
        st.caption(f"Dossier : {scope}" if scope else "Périmètre : toute la base indexée")
        st.write("TXT, Markdown, PDF avec texte, DOCX et XLSX · fichiers de 1 octet à 50 Mo.")
        st.caption("Les PDF scannés nécessitant un OCR sont signalés. Les fichiers vides ou hors limite ne sont pas traités.")
        batch = st.number_input("Fichiers par lot", min_value=1, max_value=1000, value=100)
        if st.button("Extraire le prochain lot", type="primary", disabled=job.running):
            job.start("extract", scope, limit=int(batch))
            st.rerun()
        st.caption("Relancez pour traiter le lot suivant. Les erreurs sont conservées dans l’état du système.")
    elif page == PAGES[2]:
        st.header("Rechercher et consulter")
        query = st.text_input("Search query", placeholder="Nom de fichier ou mots dans le contenu")
        extension = st.selectbox("Format", ["Tous", ".txt", ".md", ".pdf", ".docx", ".xlsx"])
        missing = st.checkbox("Show missing files (recovery)")
        if st.button("🔍 Search", type="primary"):
            st.session_state.lite_search = (query, extension, missing)
        if "lite_search" in st.session_state:
            q, ext, show_missing = st.session_state.lite_search
            results = db.search_files(query=q, extension=None if ext == "Tous" else ext,
                                      include_missing=show_missing, limit=100)
            st.subheader(f"Search Results ({len(results)} results)")
            if not results:
                st.info("Aucun résultat. Vérifiez le scan et l’extraction du contenu.")
            st.caption("Au maximum 100 résultats ; précisez la recherche pour affiner.")
            for row in results:
                with st.expander(row["filename"]):
                    st.write(f"**{row['filename']}**")
                    st.code(row["path"], language=None)
                    st.caption(f"{row.get('state', 'ACTIVE')} · {row['size_bytes']:,} octets")
                    content = row.get("content_text") or ""
                    if content:
                        st.text(content[:12000])
                        if len(content) > 12000:
                            st.caption("Aperçu limité aux 12 000 premiers caractères.")
                    else:
                        st.info("Contenu non extrait ou aucun texte disponible.")
                    if st.button("Ouvrir le dossier", key=f"lite_open_{row['id']}"):
                        from src.utils.os_open import reveal_path
                        if not reveal_path(row["path"]):
                            st.error("Impossible d’ouvrir ce dossier sur cette machine.")
    else:
        st.header("État du système")
        stats = db.get_stats()
        st.metric("Fichiers indexés", stats["total_files"])
        st.caption(f"Base : {db.db_path.resolve()}")
        from src.ingest.queue_store import ExtractionQueue
        queue = ExtractionQueue(db)
        issues = queue.issues(limit=100)
        if issues:
            st.write("Erreurs et fichiers sans texte (100 maximum)")
            st.dataframe([{"Fichier": i.get("path"), "État": i.get("outcome"),
                           "Détail": i.get("detail")} for i in issues], hide_index=True)
        else:
            st.info("Aucune erreur d’extraction enregistrée.")
        backup_dir = st.text_input("Dossier de sauvegarde", value=str(Path.home() / ".pis-backups"))
        if st.button("Sauvegarder l’index", disabled=job.running):
            try:
                from src.ops.backup import create_backup
                with st.spinner("Sauvegarde en cours…"):
                    result = create_backup(db, out_dir=Path(backup_dir).expanduser(), include_semantic=False)
                st.success(f"Sauvegarde créée : {result.archive_path}")
            except Exception as exc:
                st.error(f"Échec de la sauvegarde : {exc}")
