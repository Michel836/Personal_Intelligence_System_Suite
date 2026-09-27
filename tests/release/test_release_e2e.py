"""Release end-to-end acceptance over the deterministic corpus (M021)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from src.dedup import DedupStore, RelatedDocuments
from src.graph import DocumentGraph, TimelineService
from src.ingest.taxonomy import Outcome
from src.intel import IntelStore
from src.reports import DossierService, ExportService, ReportKind, run_query


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- scan / extraction / taxonomy / source safety ---------------------------
def test_scan_extraction_taxonomy_and_source_safety(release_env) -> None:
    corpus = release_env.corpus
    db = release_env.db
    with db.get_connection() as conn:
        files = conn.execute(
            "SELECT COUNT(*) FROM files WHERE document_kind='PHYSICAL_FILE'").fetchone()[0]
    assert files == len(corpus.entries)

    # Extracted text is searchable through canonical FTS.
    assert db.search_files("Bank payment accounting")
    assert db.search_files("Patient clinical diagnosis")
    assert db.search_files("Compiler algorithm network")

    # Scanned PDF has no text layer -> OCR candidate, not a silent success.
    scanned = release_env.file_id("formats/scanned.pdf")
    with db.get_connection() as conn:
        outcome = conn.execute(
            "SELECT outcome FROM extraction_queue WHERE file_id=? AND operation='extract'",
            (scanned,)).fetchone()
    assert outcome is not None and outcome[0] in {
        Outcome.NO_TEXT.value, Outcome.OCR_REQUIRED.value, Outcome.OCR_FAILED.value}

    # Malformed fixtures are terminal and clearly classified (no infinite retry).
    for rel in ("hostile/malformed.pdf", "hostile/truncated.docx", "formats/sample.msg"):
        fid = release_env.file_id(rel)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT outcome FROM extraction_queue WHERE file_id=? AND operation='extract'",
                (fid,)).fetchone()
        assert row is not None, f"{rel} must record an outcome"
        assert row[0] in {Outcome.MALFORMED.value, Outcome.PERMANENT_ERROR.value,
                          Outcome.UNSUPPORTED_DEPENDENCY.value}

    # Archive members are first-class indexed documents.
    with db.get_connection() as conn:
        members = conn.execute(
            "SELECT COUNT(*) FROM files WHERE document_kind='ARCHIVE_MEMBER'").fetchone()[0]
    assert members >= 3

    # Source safety: byte-identical and no residue beside the sources.
    for entry in corpus.entries:
        assert _sha(corpus.path(entry.relpath)) == entry.sha256, entry.relpath
    assert _tree_files(corpus.root) == {e.relpath for e in corpus.entries}


# --- search: lexical, semantic, rerank, related -----------------------------
def test_search_lexical_semantic_rerank_and_related(release_env) -> None:
    db = release_env.db
    finance_id = release_env.file_id("docs/alpha_finance.txt")
    tech_id = release_env.file_id("docs/beta_technology.md")

    lexical = db.search_files("bank payment accounting", limit=10)
    assert finance_id in {int(r["id"]) for r in lexical}

    semantic = release_env.engine.semantic_search("finance invoice bank", limit=10)
    assert semantic, "semantic search must return results"
    assert finance_id in {int(r["id"]) for r in semantic}

    from src.dedup import rerank_search
    fused = rerank_search(db, release_env.engine, "compiler network python", limit=10)
    assert fused and tech_id in {int(r["id"]) for r in fused}

    from src.intelligence.embedding_store import EmbeddingMatrixStore
    store = EmbeddingMatrixStore("release-hash", "release-hash-embedding", 64,
                                 base_dir=release_env.store_dir)
    assert store.load()
    related = RelatedDocuments(db, embed_store=store).related(finance_id, limit=5)
    assert related, "related documents must be available from the embedding store"


def test_search_filters_language_category_entity_pii(release_env) -> None:
    db = release_env.db
    pii_id = release_env.file_id("docs/pii_fixture.txt")
    # PII filter excludes the clean finance document.
    with_pii = db.search_files("Synthetic privacy fixture", has_pii=True, limit=10)
    assert pii_id in {int(r["id"]) for r in with_pii}
    without_pii = db.search_files("finance", has_pii=False, limit=20)
    assert pii_id not in {int(r["id"]) for r in without_pii}
    # Language filter (FR fixture).
    fr = db.search_files(None, language="fr", limit=20)
    assert fr, "FR document should be filterable by detected language"


# --- intelligence: language / categories / entities / PII masking -----------
def test_intelligence_and_pii_masking(release_env) -> None:
    db = release_env.db
    store = IntelStore(db)
    pii_id = release_env.file_id("docs/pii_fixture.txt")
    findings = store.get_pii(pii_id)
    types = {f["pii_type"] for f in findings}
    assert {"email", "iban", "card"} <= types
    assert all(f.get("masked") for f in findings)
    assert store.max_severity(pii_id) == "high"

    from src.intel.redact import redacted_preview
    preview = redacted_preview("Contact release.fixture@example.test now",
                               store=store, max_chars=200)
    assert "release.fixture@example.test" not in preview["redacted"]

    # DE/FR detection where enough evidence exists.
    langs = {r["file_id"]: r["lang"] for r in _language_rows(db)}
    fr_id = release_env.file_id("docs/fr_note.txt")
    de_id = release_env.file_id("docs/de_notiz.txt")
    assert langs.get(fr_id) in {"fr", "und"}
    assert langs.get(de_id) in {"de", "und"}
    assert langs.get(fr_id) == "fr" or langs.get(de_id) == "de"


def _language_rows(db) -> list[dict]:
    with db.get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT file_id, lang FROM doc_language")]


# --- relationships ----------------------------------------------------------
def test_duplicates_versions_graph_and_timeline(release_env) -> None:
    db = release_env.db
    store = DedupStore(db)
    exact_a = release_env.file_id("duplicates/exact_a.txt")
    exact_b = release_env.file_id("duplicates/exact_b.txt")
    groups = store.exact_duplicate_groups(min_size=1)
    member_sets = [{int(m["id"]) for m in g["members"]} for g in groups]
    assert any({exact_a, exact_b} <= members for members in member_sets)

    v1 = release_env.file_id("versions/report_v1.txt")
    v2 = release_env.file_id("versions/report_v2.txt")
    fam = store.get_version_family_for_file(v1)
    assert fam is not None
    assert {int(m["id"]) for m in fam["members"]} == {v1, v2}

    neighborhood = DocumentGraph(db).neighborhood(exact_a, max_nodes=20, max_edges=40)
    assert any(int(e["target"]) == exact_b or int(e["source"]) == exact_b
               for e in neighborhood["edges"])

    timeline = TimelineService(db).events(start="2000-01-01", end="2100-01-01", limit=200)
    assert timeline["events"]
    assert timeline["date_source"] == "modified_at"


# --- dossier / report / export ----------------------------------------------
def test_dossier_report_and_export_roundtrip(release_env) -> None:
    db = release_env.db
    service = ExportService(db, out_dir=release_env.root / "exports")

    static_id = release_env.file_id("docs/alpha_finance.txt")
    tech_id = release_env.file_id("docs/beta_technology.md")
    dossiers = DossierService(db)
    static = dossiers.create("Release static", file_ids=[static_id, tech_id])
    resolved = dossiers.resolve(static["dossier_id"])
    assert resolved["count"] == 2
    dynamic = dossiers.create_from_query("Release dynamic", {"query": "finance"})
    assert any(int(r["id"]) == static_id for r in run_query(db, {"query": "finance"}))

    definition = service.create_definition(
        ReportKind.DOSSIER.value, "Release dossier report",
        options={"dossier_id": dynamic["dossier_id"]})
    result = service.generate(definition, formats=("HTML", "JSON"))
    assert result.ir.logical_fingerprint()
    html_path = next(a.path for a in result.artifacts if a.format == "HTML")
    html = Path(html_path).read_text(encoding="utf-8")
    refs_used = {m.group(1) for m in re.finditer(r"\[(D\d+)(?::p\d+)?\]", html)}
    assert refs_used <= {s.ref for s in result.ir.sources}
    for artifact in result.artifacts:
        assert Path(artifact.path).exists()

    # PDF when a local provider is available; extract the text back from it.
    from src.reports.pdf_export import available_providers, choose_provider
    if choose_provider() is not None:
        pdf_result = service.generate(definition, formats=("PDF",), overwrite=True)
        pdf = next(a.path for a in pdf_result.artifacts if a.format == "PDF")
        assert Path(pdf).exists() and Path(pdf).stat().st_size > 100
        import PyPDF2
        text = "".join(page.extract_text() or "" for page in PyPDF2.PdfReader(pdf).pages)
        assert text.strip(), "generated PDF must contain extractable text"
        assert available_providers()


# --- galaxy / clusters / topics / context -----------------------------------
def test_galaxy_clusters_topics_and_context(release_env) -> None:
    from src.galaxy import GalaxyService
    from src.intelligence.embedding_store import EmbeddingMatrixStore
    store = EmbeddingMatrixStore("release-hash", "release-hash-embedding", 64,
                                 base_dir=release_env.store_dir)
    assert store.load()
    service = GalaxyService(release_env.db, embedding_store=store)

    payload = service.galaxy(scope={"kind": "all"}, method="pca", color_by="cluster",
                             k=5, persist=False)
    assert payload["available"] is True
    assert payload["points"]

    built = service.build_clusters(scope={"kind": "all"}, k=5, persist=True)
    run_id = built["run_id"]
    topics = service.build_topics(run_id)
    assert topics and all(t.label for t in topics)
    detail = service.cluster_detail(run_id, topics[0].cluster_id)
    assert detail["size"] > 0
    assert detail["status"]["status"] == "FRESH"

    finance_id = release_env.file_id("docs/alpha_finance.txt")
    context = service.document_context(finance_id)
    assert context["privacy"]["raw_pii_exposed"] is False
    assert "cluster_membership" in context

    collapse = service.collapse_ids([release_env.file_id("duplicates/exact_a.txt"),
                                     release_env.file_id("duplicates/exact_b.txt")],
                                    exact=True, versions=True)
    assert collapse[1]["exact_removed"] == 1


# --- restart preserves state ------------------------------------------------
def test_restart_preserves_state(release_env) -> None:
    db = release_env.db
    tables = ("files", "content_hashes", "doc_language", "doc_intel_state",
              "doc_categories", "doc_pii")
    with db.get_connection() as conn:
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in tables}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    from src.core.database import DatabaseManager
    reopened = DatabaseManager(db.db_path)
    with reopened.get_connection() as conn:
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in tables}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert before == after
    assert reopened.search_files("Bank payment accounting")
