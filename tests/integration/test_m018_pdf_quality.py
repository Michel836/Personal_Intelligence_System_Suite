"""Synthetic PDF quality checks (M018, phase 30).

Builds a report exercising FR accents, German umlauts/ß, English, tables,
multi-page content, long URLs, page breaks, citations, masked PII, a missing
source and a missing image, then verifies the rendered PDF opens and its text
can be extracted.
"""
from __future__ import annotations

import pytest

from src.reports.html_export import render_html
from src.reports.models import (
    Block,
    BlockType,
    PrivacyMode,
    ReportDefinition,
    ReportIR,
    Section,
    SourceRef,
)
from src.reports.pdf_export import available_providers, render_pdf
from src.reports.privacy import mask_text


def _ir() -> ReportIR:
    definition = ReportDefinition(
        report_id="rpt_pdf_quality", kind="SEARCH", title="Rapport qualité — Bericht",
        privacy_mode=PrivacyMode.MASK_PII.value)
    ir = ReportIR(definition=definition)
    ir.sources = [
        SourceRef(ref="D1", file_id=1, label="café_résumé_Straße.txt", path="<redacted>/x.txt",
                  date="2024-05-06", date_source="modified_at", provenance="KNOWN"),
        SourceRef(ref="D2", file_id=2, label="missing.txt", unavailable=True,
                  provenance="UNAVAILABLE"),
    ]
    long_url = "https://example.com/" + "segment/" * 20 + "fin"
    rows = [[f"row {i}", "é" * 3, "ß", f"[D1] {i}"] for i in range(200)]
    ir.sections = [
        Section(id="s1", title="Résumé — Zusammenfassung", blocks=[
            Block(BlockType.PARAGRAPH.value,
                  {"text": mask_text(
                      "Français: café, œuf, à, é, ç. Deutsch: Straße, Größe, ü, ö, ß. "
                      "English ready. Contact jean.dupont@example.com.",
                      PrivacyMode.MASK_PII.value), "citations": ["D1"]}),
            Block(BlockType.PARAGRAPH.value, {"text": long_url}),
            Block(BlockType.WARNING.value, {"text": "Source [D2] is unavailable."}),
            Block(BlockType.IMAGE.value, {"reason": "unavailable"}),
        ]),
        Section(id="s2", title="Long table", blocks=[
            Block(BlockType.TABLE.value, {
                "columns": ["Row", "A", "B", "Ref"], "rows": rows})]),
    ]
    return ir


def test_pdf_quality_renders_and_extracts() -> None:
    if not any(v["available"] for v in available_providers().values()):
        pytest.skip("no local PDF provider")
    import tempfile
    from pathlib import Path
    ir = _ir()
    html = render_html(ir)
    out = Path(tempfile.mkdtemp()) / "quality.pdf"
    result = render_pdf(html, out)
    assert result.ok, result.error
    assert result.pages >= 2, f"expected multi-page, got {result.pages}"
    from PyPDF2 import PdfReader
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(out)).pages)
    # Unicode across FR/DE survives.
    for token in ("café", "œuf", "Straße", "Größe", "English"):
        assert token in text, token
    # Long URL domain present (some renderers wrap/space the path).
    assert "example.com" in text
    # Masked PII: raw address must not be present.
    assert "jean.dupont@example.com" not in text
    # Citation and missing-source warning survive.
    assert "[D1]" in text
    assert "unavailable" in text.lower()
