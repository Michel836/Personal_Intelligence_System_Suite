"""Optional OCR fallback using the system Tesseract (M009H.7).

Disabled by default; enabled with ``PIS_OCR_ENABLED=1``. Bounded by size, page
count and per-call timeout, with language configuration and failure isolation.
Never OCRs large media blindly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from .base import BaseExtractor, ExtractionResult

try:
    import pytesseract
    from PIL import Image

    OCR_LIBS_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency guard
    OCR_LIBS_AVAILABLE = False
    logger.debug("pytesseract/Pillow not available - OCR disabled")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXTENSIONS = {".pdf"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def ocr_enabled() -> bool:
    return os.environ.get("PIS_OCR_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def ocr_languages() -> str:
    return os.environ.get("PIS_OCR_LANGS", "fra+deu+eng")


def ocr_max_pages() -> int:
    return max(1, _env_int("PIS_OCR_MAX_PAGES", 5))


def ocr_timeout() -> int:
    return max(1, _env_int("PIS_OCR_TIMEOUT", 30))


def ocr_max_bytes() -> int:
    return max(1, _env_int("PIS_OCR_MAX_BYTES", 25 * 1024 * 1024))


def tesseract_available() -> bool:
    return OCR_LIBS_AVAILABLE and shutil.which("tesseract") is not None


def _ocr_image_file(path: Path, langs: str) -> str:
    with Image.open(path) as image:
        return pytesseract.image_to_string(image, lang=langs, timeout=ocr_timeout())


def _render_pdf_pages(path: Path, out_dir: Path, max_pages: int) -> list[Path]:
    prefix = out_dir / "page"
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        subprocess.run(
            [pdftoppm, "-f", "1", "-l", str(max_pages), "-r", "200", "-png", str(path), str(prefix)],
            capture_output=True, timeout=ocr_timeout() * max_pages, check=False,
        )
        return sorted(out_dir.glob("page*.png"))
    try:
        from pdf2image import convert_from_path

        images = convert_from_path(str(path), first_page=1, last_page=max_pages)
        rendered = []
        for idx, image in enumerate(images):
            target = out_dir / f"page{idx}.png"
            image.save(target)
            rendered.append(target)
        return rendered
    except Exception as exc:  # pragma: no cover - dependency/env dependent
        logger.debug(f"PDF rasterisation unavailable: {exc}")
        return []


def ocr_file(path: Path, *, langs: Optional[str] = None) -> ExtractionResult:
    """OCR an image or scanned PDF. Returns a failed result when disabled/unavailable."""
    start = time.time()
    if not ocr_enabled():
        return ExtractionResult(success=False, error="OCR disabled", extraction_time=time.time() - start)
    if not tesseract_available():
        return ExtractionResult(success=False, error="tesseract unavailable", extraction_time=time.time() - start)
    suffix = path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS | PDF_EXTENSIONS:
        return ExtractionResult(success=False, error=f"OCR unsupported: {suffix}", extraction_time=time.time() - start)
    try:
        if path.stat().st_size > ocr_max_bytes():
            return ExtractionResult(success=False, error="file exceeds OCR size limit", extraction_time=time.time() - start)
        langs = langs or ocr_languages()
        if suffix in IMAGE_EXTENSIONS:
            text = _ocr_image_file(path, langs)
        else:
            with tempfile.TemporaryDirectory(prefix="pis-ocr-") as tmp:
                pages = _render_pdf_pages(path, Path(tmp), ocr_max_pages())
                text = "\n".join(_ocr_image_file(page, langs) for page in pages)
        text = text.strip()
        if not text:
            return ExtractionResult(success=False, error="No text recognised", extraction_time=time.time() - start)
        return ExtractionResult(success=True, content=text, metadata={"ocr": True, "langs": langs}, extraction_time=time.time() - start)
    except Exception as exc:  # noqa: BLE001 - failure isolation
        logger.debug(f"OCR failed for {path}: {exc}")
        return ExtractionResult(success=False, error=f"OCR error: {exc}", extraction_time=time.time() - start)


class OcrExtractor(BaseExtractor):
    """Extractor facade for images / scanned PDFs (disabled by default)."""

    def __init__(self) -> None:
        super().__init__()
        self.supported_extensions = IMAGE_EXTENSIONS | PDF_EXTENSIONS

    def can_extract(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions and file_path.is_file()

    def extract_content(self, file_path: Path) -> ExtractionResult:
        return ocr_file(file_path)
