"""HTML/PDF export, manifest, output-dir safety and reproducibility (M018)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.reports.export import ExportService, default_export_dir, safe_component
from src.reports.html_export import MAX_TABLE_ROWS, render_html
from src.reports.models import (
    Block,
    BlockType,
    PrivacyMode,
    ReportDefinition,
    ReportIR,
    Section,
)
from src.reports.pdf_export import available_providers, render_pdf


def _add(db: DatabaseManager, fid: int, path: str, text: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
            "state, document_kind, content_extracted) VALUES (?, ?, ?, '.txt', 10, "
            "'2024-01-01 00:00:00', 'ACTIVE', 'PHYSICAL_FILE', 1)",
            (fid, path, Path(path).name))
        conn.commit()
    db.update_content(fid, text)


def _definition(**kw) -> ReportDefinition:
    base = {"report_id": "rpt_test", "kind": "SEARCH", "title": "Test report"}
    base.update(kw)
    return ReportDefinition(**base)


# --- HTML safety -------------------------------------------------------------
def test_html_is_escaped_and_has_no_remote_assets() -> None:
    d = _definition()
    ir = ReportIR(definition=d)
    ir.sections = [Section(id="s", title="S", blocks=[
        Block(BlockType.PARAGRAPH.value, {"text": "<script>alert(1)</script> & <b>bold</b>"})])]
    html = render_html(ir)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<script" not in html.lower()
    assert 'src="http' not in html and "@import" not in html
    assert "@page" in html  # print layout preserved


def test_html_table_is_bounded() -> None:
    ir = ReportIR(definition=_definition())
    rows = [[i] for i in range(MAX_TABLE_ROWS + 25)]
    ir.sections = [Section(id="t", title="T", blocks=[
        Block(BlockType.TABLE.value, {"columns": ["n"], "rows": rows})])]
    html = render_html(ir)
    assert "Table truncated" in html


def test_html_missing_image_is_reported_not_broken() -> None:
    ir = ReportIR(definition=_definition())
    ir.sections = [Section(id="i", title="I", blocks=[
        Block(BlockType.IMAGE.value, {"reason": "unavailable"})])]
    html = render_html(ir)
    assert "[image omitted" in html


# --- output directory safety -------------------------------------------------
def test_safe_component_and_traversal(tmp_path) -> None:
    assert "/" not in safe_component("../../etc/passwd")
    assert not safe_component("../../etc/passwd").startswith(".")
    assert safe_component("") == "report"
    db = DatabaseManager(tmp_path / "db.db")
    svc = ExportService(db, out_dir=tmp_path / "exports")
    with pytest.raises(ValueError):
        svc._safe_path("../../escape.html")


def test_default_export_dir_is_outside_repo(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PIS_EXPORT_DIR", str(tmp_path / "x"))
    assert default_export_dir() == tmp_path / "x"
    monkeypatch.delenv("PIS_EXPORT_DIR", raising=False)
    assert default_export_dir() == Path.home() / ".pis-exports"


# --- generation, manifest, history ------------------------------------------
def test_generate_html_json_manifest_and_checksum(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", "alpha token")
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition("SEARCH", "Alpha", query={"query": "alpha"})
    result = svc.generate(definition, formats=("HTML", "JSON"))
    formats = {a.format for a in result.artifacts}
    assert formats == {"HTML", "JSON"}
    assert result.manifest_path and Path(result.manifest_path).is_file()
    manifest = json.loads(Path(result.manifest_path).read_text())
    assert manifest["report_id"] == definition.report_id
    assert manifest["privacy_mode"] == "FULL_LOCAL"
    assert manifest["logical_fingerprint"] == result.ir.logical_fingerprint()
    assert 1 in manifest["source_document_ids"]
    for artifact in result.artifacts:
        assert Path(artifact.path).is_file()
        assert artifact.size_bytes > 0 and len(artifact.checksum) == 64
    # History recorded.
    history = svc.store.artifacts_for(definition.report_id)
    assert {h["format"] for h in history} == {"HTML", "JSON"}
    assert all(h["exists"] for h in history)


def test_regeneration_is_logically_reproducible(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", "stable content")
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition("SEARCH", "Stable", query={"query": "stable"})
    first = svc.generate(definition, formats=("JSON",))
    second = svc.regenerate(definition.report_id, formats=("JSON",))
    assert first.ir.logical_fingerprint() == second.ir.logical_fingerprint()
    assert first.artifacts[0].path != second.artifacts[0].path  # no clobber
    assert Path(first.artifacts[0].path).is_file()


def test_deleted_source_is_listed_unavailable(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", "ghost content")
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition("SEARCH", "Ghost", document_ids=[1])
    svc.save_definition(definition)
    # Document disappears after the definition was saved.
    with db.get_connection() as conn:
        conn.execute("DELETE FROM files WHERE id=1")
        conn.commit()
    result = svc.regenerate(definition.report_id, formats=("JSON",))
    assert result is not None
    assert result.ir.sources[0].unavailable is True


def test_prune_missing_artifacts(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", "alpha")
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition("SEARCH", "T", query={"query": "alpha"})
    result = svc.generate(definition, formats=("HTML",))
    Path(result.artifacts[0].path).unlink()
    removed = svc.store.prune_missing_artifacts()
    assert removed == 1
    assert svc.store.artifacts_for(definition.report_id) == []


# --- privacy at export -------------------------------------------------------
def test_metadata_only_excludes_excerpts(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", "SECRETBODY token")
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition("SEARCH", "Meta", query={"query": "token"},
                                       privacy_mode=PrivacyMode.METADATA_ONLY.value)
    result = svc.generate(definition, formats=("HTML",))
    html = Path(result.artifacts[0].path).read_text()
    assert "SECRETBODY" not in html


# --- PDF provider chain ------------------------------------------------------
def test_export_pdf_provider_failure_is_explicit(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", "alpha token")
    svc = ExportService(db, out_dir=tmp_path / "exports", pdf_provider="not-a-provider")
    definition = svc.create_definition("SEARCH", "Broken PDF", query={"query": "alpha"})
    result = svc.generate(definition, formats=("HTML", "PDF"))
    assert all(a.format != "PDF" for a in result.artifacts)
    assert result.pdf is not None and result.pdf.ok is False
    assert any("PDF not generated" in w for w in result.warnings)
    # HTML still produced; no silent content-changing fallback.
    assert any(a.format == "HTML" for a in result.artifacts)


def test_pdf_provider_detection_and_failure() -> None:
    providers = available_providers()
    assert set(providers) == {"weasyprint", "libreoffice", "chrome"}
    assert any(v["available"] for v in providers.values())
    # Explicit unavailable provider fails closed, no silent HTML fallback.
    result = render_pdf("<html><body>x</body></html>", Path("/tmp/m018-nope.pdf"),
                        provider="not-a-provider", allow_fallback=False)
    assert result.ok is False and result.error


@pytest.mark.skipif(
    not (available_providers()["libreoffice"]["available"]
         or available_providers()["chrome"]["available"]
         or available_providers()["weasyprint"]["available"]),
    reason="no PDF provider")
def test_pdf_render_and_text_extraction(tmp_path) -> None:
    ir = ReportIR(definition=_definition(title="Rapport — Café Straße"))
    ir.sections = [Section(id="s", title="Résumé", blocks=[
        Block(BlockType.PARAGRAPH.value, {"text": "Unicode é à ö ü ß œuf."})])]
    html = render_html(ir)
    out = tmp_path / "out.pdf"
    result = render_pdf(html, out, provider="libreoffice")
    assert result.ok, result.error
    assert result.pages >= 1
    from PyPDF2 import PdfReader
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(out)).pages)
    assert "Café" in text and "Straße" in text
