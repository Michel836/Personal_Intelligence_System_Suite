"""OpenDocument (ODF) extractor for .odt / .ods files (M009H.6).

Bounded: enforces a size limit, isolates malformed files (returns a failed
``ExtractionResult`` instead of raising), and never aborts a batch.
"""
from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from .base import BaseExtractor, ExtractionResult

try:
    from odf import table as odf_table
    from odf import teletype
    from odf import text as odf_text
    from odf.opendocument import load as odf_load

    ODF_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency guard
    ODF_AVAILABLE = False
    logger.warning("odfpy not available - ODT/ODS extraction disabled")


MAX_ODF_BYTES = 50 * 1024 * 1024


class OdfExtractor(BaseExtractor):
    """Extract text from OpenDocument Text (.odt) and Spreadsheet (.ods)."""

    def __init__(self, max_bytes: int = MAX_ODF_BYTES):
        super().__init__()
        self.supported_extensions = {".odt", ".ods"}
        self.max_bytes = max_bytes

    def can_extract(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions and file_path.is_file()

    def extract_content(self, file_path: Path) -> ExtractionResult:
        start = time.time()
        if not ODF_AVAILABLE:
            return ExtractionResult(
                success=False, error="odfpy not installed", extraction_time=time.time() - start
            )
        try:
            if file_path.stat().st_size > self.max_bytes:
                return ExtractionResult(
                    success=False,
                    error=f"ODF file exceeds size limit ({self.max_bytes} bytes)",
                    extraction_time=time.time() - start,
                )
            document = odf_load(str(file_path))
            if file_path.suffix.lower() == ".ods":
                content, metadata = self._extract_ods(document)
            else:
                content, metadata = self._extract_odt(document)
            if not content.strip():
                return ExtractionResult(
                    success=False, content="", metadata=metadata,
                    error="No text content found", extraction_time=time.time() - start,
                )
            return ExtractionResult(
                success=True, content=content, metadata=metadata,
                extraction_time=time.time() - start,
            )
        except Exception as exc:  # noqa: BLE001 - malformed file isolation
            logger.debug(f"ODF extraction failed for {file_path}: {exc}")
            return ExtractionResult(
                success=False, error=f"ODF extraction error: {exc}",
                extraction_time=time.time() - start,
            )

    @staticmethod
    def _extract_odt(document):
        paragraphs = document.getElementsByType(odf_text.P)
        text = "\n".join(teletype.extractText(p) for p in paragraphs)
        return text, {"format": "odt", "paragraphs": len(paragraphs)}

    @staticmethod
    def _extract_ods(document):
        lines = []
        tables = document.getElementsByType(odf_table.Table)
        for table in tables:
            lines.append(f"# Sheet: {table.getAttribute('name') or 'Sheet'}")
            for row in table.getElementsByType(odf_table.TableRow):
                cells = [teletype.extractText(c) for c in row.getElementsByType(odf_table.TableCell)]
                if any(cell.strip() for cell in cells):
                    lines.append("\t".join(cells))
        return "\n".join(lines), {"format": "ods", "tables": len(tables), "rows": len(lines)}
