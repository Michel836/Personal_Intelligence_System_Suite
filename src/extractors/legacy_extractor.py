"""Bounded legacy format extraction via installed local tools (M017).

Layered strategy: native/installed tool -> LibreOffice headless -> explicit
UNSUPPORTED_DEPENDENCY. Conversions always run on temp copies; source files are
never modified. No shell, hard timeout, bounded output.
"""
from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from ..ingest import tools
from .base import BaseExtractor, ExtractionResult

MAX_OUTPUT_CHARS = 5_000_000


class LegacyExtractor(BaseExtractor):
    """DOC/XLS/PPT/RTF/WPD via antiword, catdoc, xls2csv, catppt, unrtf, LibreOffice."""

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.supported_extensions = {".doc", ".xls", ".ppt", ".rtf", ".wpd", ".wps"}

    def can_extract(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions and file_path.is_file()

    # (tool, argv prefix) then LibreOffice fallback
    _FILTERS: dict[str, list[list[str]]] = {
        ".doc": [["antiword"], ["catdoc"]],
        ".xls": [["xls2csv"]],
        ".ppt": [["catppt"]],
        ".rtf": [["unrtf", "--text", "--nopict"]],
        ".wpd": [],
        ".wps": [],
    }

    def extract_content(self, file_path: Path) -> ExtractionResult:
        start = time.time()
        ext = file_path.suffix.lower()
        errors: list[str] = []
        for prefix in self._FILTERS.get(ext, []):
            if not tools.available(prefix[0]):
                errors.append(f"{prefix[0]} unavailable")
                continue
            res = tools.run_filter_stdout([*prefix, str(file_path)])
            if res.ok and res.output.strip():
                text = res.output.strip()
                if prefix[0] == "unrtf":
                    text = "\n".join(ln for ln in text.splitlines()
                                      if not ln.startswith("###") and set(ln.strip()) not in ({"-"}, {"="}))
                text = text.strip()[:MAX_OUTPUT_CHARS]
                return ExtractionResult(success=True, content=text,
                                        metadata={"legacy_tool": prefix[0]},
                                        extraction_time=time.time() - start)
            errors.append(f"{prefix[0]}: {res.error or 'empty output'}")
        # LibreOffice fallback
        if tools.available("libreoffice") or tools.available("soffice"):
            res = tools.convert_with_libreoffice(file_path)
            if res.ok and res.output.strip():
                return ExtractionResult(success=True, content=res.output.strip()[:MAX_OUTPUT_CHARS],
                                        metadata={"legacy_tool": "libreoffice"},
                                        extraction_time=time.time() - start)
            errors.append(f"libreoffice: {res.error or 'empty output'}")
        if not errors or all("unavailable" in e for e in errors):
            return ExtractionResult(
                success=False,
                error=f"legacy {ext} unsupported dependency: no local converter available",
                extraction_time=time.time() - start)
        logger.debug(f"legacy extraction failed for {ext}: {errors[:2]}")
        return ExtractionResult(success=False, error=f"legacy {ext} failed: {errors[0]}",
                                extraction_time=time.time() - start)
