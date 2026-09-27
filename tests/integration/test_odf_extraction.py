"""ODF (.odt/.ods) extraction tests (M009H.6)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("odf")

from src.extractors.manager import ExtractionManager
from src.extractors.odf_extractor import MAX_ODF_BYTES, OdfExtractor


def _make_odt(path: Path, text: str) -> None:
    from odf.opendocument import OpenDocumentText
    from odf.text import P

    doc = OpenDocumentText()
    doc.text.addElement(P(text=text))
    doc.save(str(path))


def _make_ods(path: Path) -> None:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    doc = OpenDocumentSpreadsheet()
    table = Table(name="Feuille1")
    for values in (["montant", "devise"], ["15000", "EUR"]):
        row = TableRow()
        for value in values:
            cell = TableCell()
            cell.addElement(P(text=value))
            row.addElement(cell)
        table.addElement(row)
    doc.spreadsheet.addElement(table)
    doc.save(str(path))


def test_odt_extraction(tmp_path: Path) -> None:
    path = tmp_path / "contrat.odt"
    _make_odt(path, "Contrat de bail résumé du marché")
    result = OdfExtractor().extract_content(path)
    assert result.success
    assert "Contrat de bail" in result.content


def test_ods_extraction(tmp_path: Path) -> None:
    path = tmp_path / "budget.ods"
    _make_ods(path)
    result = OdfExtractor().extract_content(path)
    assert result.success
    assert "EUR" in result.content
    assert "15000" in result.content


def test_manager_selects_odf_extractor(tmp_path: Path) -> None:
    path = tmp_path / "note.odt"
    _make_odt(path, "contenu odf")
    manager = ExtractionManager()
    result = manager.extract_single(path)
    assert result.success


def test_malformed_odf_is_isolated(tmp_path: Path) -> None:
    path = tmp_path / "broken.odt"
    path.write_bytes(b"not a zip archive")
    result = OdfExtractor().extract_content(path)
    assert result.success is False
    assert result.error


def test_size_limit(tmp_path: Path) -> None:
    path = tmp_path / "big.odt"
    _make_odt(path, "x")
    result = OdfExtractor(max_bytes=1).extract_content(path)
    assert result.success is False
    assert "size limit" in (result.error or "")
    assert MAX_ODF_BYTES > 1
