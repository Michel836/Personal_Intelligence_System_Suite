"""End-to-end M018 report/dossier/export integration."""
from __future__ import annotations

import re
from pathlib import Path

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.core.volume import VolumeInfo
from src.reports import (
    CitationRegistry,
    DossierService,
    ExportService,
    PrivacyMode,
    ReportKind,
    run_query,
)
from src.reports.reconstruction import reconstruct_timeline

CONTENT = {
    "cancer_fr.txt": (
        "Bonjour, étude cancer immunotherapy. Contact jean.dupont@example.com "
        "IBAN FR76 3000 6000 0112 3456 7890 189. Rendez-vous à Lyon."
    ),
    "cancer_de.txt": (
        "Krebsforschung Studie. Kontakt max.mustermann@example.de Tel +49 30 1234567. "
        "Straße München."
    ),
    "notes.txt": "Miscellaneous unrelated notes about weather.",
}


def _seed(tmp_path: Path) -> DatabaseManager:
    root = tmp_path / "corpus"
    root.mkdir()
    for name, text in CONTENT.items():
        (root / name).write_text(text, encoding="utf-8")
    db = DatabaseManager(tmp_path / "files.db")
    result = ScanService(db).run(ScanRequest(
        root=root, batch_size=10,
        volume=VolumeInfo(stable_key="M18", device="M18", mountpoint=str(tmp_path),
                          is_available=True)))
    assert result.status == "COMPLETED"
    for row in db.search_files(None, limit=50):
        db.update_content(row["id"], CONTENT[Path(row["path"]).name])
    return db


def _pii_doc_id(db: DatabaseManager) -> int:
    return next(int(r["id"]) for r in db.search_files("Krebsforschung", limit=5))


def _service(tmp_path: Path, db: DatabaseManager) -> ExportService:
    return ExportService(db, out_dir=tmp_path / "exports")


# --- every report kind -------------------------------------------------------
def test_all_report_kinds_build_and_cite(tmp_path) -> None:
    db = _seed(tmp_path)
    from src.intel import IntelPipeline
    IntelPipeline(db).run(force=True)
    from src.ingest.queue_store import ExtractionQueue
    ExtractionQueue(db).record(999999, "MALFORMED", detail="synthetic fixture")
    svc = _service(tmp_path, db)

    dossier = DossierService(db).create("All docs", mode="DYNAMIC", query={"query": "cancer"})
    definitions = [
        svc.create_definition(ReportKind.SEARCH.value, "Search", query={"query": "cancer"}),
        svc.create_definition(ReportKind.DOSSIER.value, "Dossier",
                              options={"dossier_id": dossier["dossier_id"]}),
        svc.create_definition(ReportKind.TIMELINE.value, "Timeline",
                              query={"start": "2000-01-01", "end": "2100-01-01"}),
        svc.create_definition(ReportKind.DUPLICATES.value, "Dup",
                              document_ids=[_pii_doc_id(db)]),
        svc.create_definition(ReportKind.ENTITY_CATEGORY.value, "Entity",
                              options={"limit": 50}),
        svc.create_definition(ReportKind.PII_SUMMARY.value, "PII summary"),
        svc.create_definition(ReportKind.INGESTION.value, "Ingestion"),
        svc.create_definition(ReportKind.PROJECT.value, "Project",
                              document_ids=[int(r["id"]) for r in db.search_files(None, limit=10)]),
    ]
    for definition in definitions:
        result = svc.generate(definition, formats=("HTML", "JSON"))
        html_path = next(a.path for a in result.artifacts if a.format == "HTML")
        html = Path(html_path).read_text(encoding="utf-8")
        # No dangling citation: every [Dn] used resolves to a registered source.
        refs_used = {m.group(1) for m in re.finditer(r"\[(D\d+)(?::p\d+)?\]", html)}
        appendix_refs = {s.ref for s in result.ir.sources}
        assert refs_used <= appendix_refs
        for ref in appendix_refs:
            assert result.ir.source_by_ref(ref) is not None


def test_citation_maps_to_correct_document(tmp_path) -> None:
    db = _seed(tmp_path)
    svc = _service(tmp_path, db)
    definition = svc.create_definition(ReportKind.SEARCH.value, "Map", query={"query": "Krebsforschung"})
    result = svc.generate(definition, formats=("JSON",))
    src = result.ir.sources[0]
    with db.get_connection() as conn:
        row = conn.execute("SELECT filename FROM files WHERE id=?", (src.file_id,)).fetchone()
    assert row["filename"] == "cancer_de.txt"
    assert src.label == "cancer_de.txt"


# --- privacy end to end ------------------------------------------------------
def test_mask_pii_report_masks_content_and_paths(tmp_path) -> None:
    db = _seed(tmp_path)
    svc = _service(tmp_path, db)
    definition = svc.create_definition(ReportKind.SEARCH.value, "Mask",
                                       query={"query": "Krebsforschung"},
                                       privacy_mode=PrivacyMode.MASK_PII.value)
    result = svc.generate(definition, formats=("HTML",))
    html = Path(result.artifacts[0].path).read_text(encoding="utf-8")
    assert "max.mustermann@example.de" not in html
    assert "+49 30 1234567" not in html


def test_omit_high_sensitivity_omits_document(tmp_path) -> None:
    db = _seed(tmp_path)
    from src.intel import IntelPipeline, IntelStore
    IntelPipeline(db).run(force=True)
    high = [fid for fid in (int(r["id"]) for r in db.search_files(None, limit=10))
            if IntelStore(db).max_severity(fid) == "high"]
    if not high:
        # Ensure at least one high-sensitivity doc for the assertion.
        IntelStore(db).set_pii(_pii_doc_id(db), [{
            "type": "iban", "severity": "high", "count": 1, "confidence": 0.9,
            "detector": "iban", "fingerprint": "fp", "masked": "***"}])
        high = [_pii_doc_id(db)]
    svc = _service(tmp_path, db)
    definition = svc.create_definition(
        ReportKind.SEARCH.value, "Omit", document_ids=high,
        privacy_mode=PrivacyMode.OMIT_HIGH_SENSITIVITY.value)
    result = svc.generate(definition, formats=("JSON",))
    assert result.ir.omitted, "high-sensitivity document must be listed as omitted"
    assert all(s.file_id not in high for s in result.ir.sources) or not result.ir.sources


# --- reproducibility ---------------------------------------------------------
def test_same_definition_is_logically_reproducible(tmp_path) -> None:
    db = _seed(tmp_path)
    svc = _service(tmp_path, db)
    definition = svc.create_definition(ReportKind.SEARCH.value, "Repro",
                                       query={"query": "cancer"})
    first = svc.generate(definition, formats=("JSON",))
    second = svc.regenerate(definition.report_id, formats=("JSON",))
    assert first.ir.logical_fingerprint() == second.ir.logical_fingerprint()
    m1 = svc.store.artifacts_for(definition.report_id)
    assert m1 and all(h["exists"] for h in m1)


# --- search/timeline/graph to dossier ---------------------------------------
def test_search_to_dossier_and_snapshot(tmp_path) -> None:
    db = _seed(tmp_path)
    svc = DossierService(db)
    query = {"query": "cancer"}
    rows = run_query(db, query)
    dossier = svc.create_from_query("Cancer project", query)
    assert {m["file_id"] for m in svc.resolve(dossier["dossier_id"])["members"]} == {
        int(r["id"]) for r in rows}
    frozen = svc.freeze(dossier["dossier_id"])
    assert frozen["frozen_count"] == len(rows)
    # Manual add wins over the query.
    other = next(int(r["id"]) for r in db.search_files("weather", limit=5))
    svc.add_documents(dossier["dossier_id"], [other])
    assert other in {m["file_id"] for m in svc.resolve(dossier["dossier_id"])["members"]}


def test_timeline_selection_to_dossier(tmp_path) -> None:
    db = _seed(tmp_path)
    registry = CitationRegistry()
    pack = reconstruct_timeline(db, start="2000-01-01", end="2100-01-01",
                                mode=PrivacyMode.FULL_LOCAL.value, registry=registry)
    ids = [i["file_id"] for i in pack.items]
    assert ids
    dossier = DossierService(db).create("Timeline slice", file_ids=ids)
    resolved = DossierService(db).resolve(dossier["dossier_id"])
    assert {m["file_id"] for m in resolved["members"]} == set(ids)
    dates = {i["date_source"] for i in pack.items}
    assert dates <= {"modified_at", "created_at", "email_header", "filename_version_marker"}


def test_graph_neighborhood_to_dossier(tmp_path) -> None:
    db = _seed(tmp_path)
    from src.graph import RelationService
    from src.intel import IntelPipeline
    IntelPipeline(db).run(force=True)
    fid = _pii_doc_id(db)
    neighborhood = RelationService(db).neighborhood(fid, depth=1, max_nodes=20, max_edges=40)
    node_ids = [n["id"] for n in neighborhood["nodes"]]
    assert node_ids
    dossier = DossierService(db).create("Neighborhood", file_ids=[int(i) for i in node_ids])
    resolved = DossierService(db).resolve(dossier["dossier_id"])
    assert len(resolved["members"]) == len(node_ids)
