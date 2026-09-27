"""Bounded CHM extraction via the local 7-Zip tool (M017).

Extraction happens in a controlled temp directory, bounded by file count and
output size, with a hard timeout. If 7z is unavailable the outcome is an explicit
UNSUPPORTED_DEPENDENCY (never a silent failure).
"""
from __future__ import annotations

import time
from pathlib import Path

from ..ingest import tools
from .base import BaseExtractor, ExtractionResult
from .email_extractor import html_to_text

MAX_FILES = 500
MAX_CHARS = 5_000_000
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024
_TEXT_SUFFIXES = (".html", ".htm", ".xhtml", ".txt")


class ChmExtractor(BaseExtractor):
    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.supported_extensions = {".chm"}

    def can_extract(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions and file_path.is_file()

    def extract_content(self, file_path: Path) -> ExtractionResult:
        start = time.time()
        if not (tools.available("7z") or tools.available("7za")):
            return ExtractionResult(success=False,
                                    error="CHM unsupported dependency: 7z not installed",
                                    extraction_time=time.time() - start)
        import tempfile
        seven = tools.which("7z") or tools.which("7za")
        if not seven:
            return ExtractionResult(success=False,
                                    error="CHM unsupported dependency: 7z not installed",
                                    extraction_time=time.time() - start)
        with tempfile.TemporaryDirectory(prefix="pis-chm-") as tmp:
            copy = Path(tmp) / file_path.name
            try:
                import shutil
                shutil.copy2(file_path, copy)
            except OSError as exc:
                return ExtractionResult(success=False, error=f"CHM copy failed: {exc}",
                                        extraction_time=time.time() - start)
            out_dir = Path(tmp) / "out"
            res = tools.run_tool([seven, "x", "-y", f"-o{out_dir}", str(copy)], timeout=90)
            if not res.ok and not out_dir.exists():
                return ExtractionResult(success=False, error=f"CHM extraction failed: {res.error}",
                                        extraction_time=time.time() - start)
            extracted_bytes = sum(p.stat().st_size for p in out_dir.rglob("*")
                                  if p.is_file())
            if extracted_bytes > MAX_EXTRACTED_BYTES:
                return ExtractionResult(
                    success=False,
                    error="CHM resource limit: extracted size exceeds cap",
                    extraction_time=time.time() - start)
            parts = []
            total = 0
            count = 0
            for p in sorted(out_dir.rglob("*")):
                if count >= MAX_FILES or total >= MAX_CHARS:
                    break
                if p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES:
                    count += 1
                    try:
                        raw = p.read_bytes().decode("utf-8", "replace")
                    except Exception:
                        continue
                    text = html_to_text(raw)
                    if text:
                        parts.append(text)
                        total += len(text)
            content = "\n\n".join(parts)[:MAX_CHARS].strip()
            return ExtractionResult(success=True, content=content,
                                    metadata={"format": "CHM", "sections": count},
                                    extraction_time=time.time() - start)
