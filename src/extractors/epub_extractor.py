"""Native EPUB extraction (M017): zip + HTML, stdlib only, bounded."""
from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path

from .base import BaseExtractor, ExtractionResult
from .email_extractor import html_to_text

MAX_ENTRIES = 3000
MAX_CHARS = 5_000_000
MAX_ENTRY_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
_TEXT_SUFFIXES = (".xhtml", ".html", ".htm", ".xml")


class EpubExtractor(BaseExtractor):
    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.supported_extensions = {".epub"}

    def can_extract(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions and file_path.is_file()

    def extract_content(self, file_path: Path) -> ExtractionResult:
        start = time.time()
        try:
            with zipfile.ZipFile(file_path) as zf:
                names = zf.namelist()
                if len(names) > MAX_ENTRIES:
                    return ExtractionResult(success=False, error="resource limit: too many entries",
                                            extraction_time=time.time() - start)
                title = creator = None
                total_bytes = 0
                for name in names:
                    if name.lower().endswith(".opf"):
                        try:
                            if zf.getinfo(name).file_size > MAX_ENTRY_BYTES:
                                continue
                            opf = zf.read(name).decode("utf-8", "replace")
                            m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.S | re.I)
                            title = m.group(1).strip() if m else None
                            m = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", opf, re.S | re.I)
                            creator = m.group(1).strip() if m else None
                        except Exception:
                            pass
                        break
                parts = []
                total = 0
                for name in names:
                    if not name.lower().endswith(_TEXT_SUFFIXES):
                        continue
                    try:
                        if zf.getinfo(name).file_size > MAX_ENTRY_BYTES:
                            continue
                        raw = zf.read(name).decode("utf-8", "replace")
                    except Exception:
                        continue
                    total_bytes += len(raw)
                    if total_bytes > MAX_TOTAL_BYTES:
                        break
                    text = html_to_text(raw)
                    if text:
                        parts.append(text)
                        total += len(text)
                    if total >= MAX_CHARS:
                        break
            content = "\n\n".join(parts)[:MAX_CHARS].strip()
            metadata = {"format": "EPUB", "title": title, "creator": creator,
                        "sections": len(parts)}
            return ExtractionResult(success=True, content=content, metadata=metadata,
                                    extraction_time=time.time() - start)
        except zipfile.BadZipFile:
            return ExtractionResult(success=False, error="EPUB malformed: not a zip container",
                                    extraction_time=time.time() - start)
        except Exception as exc:  # noqa: BLE001
            return ExtractionResult(success=False, error=f"EPUB error: {exc}",
                                    extraction_time=time.time() - start)
