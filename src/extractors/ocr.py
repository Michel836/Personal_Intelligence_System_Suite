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
from typing import Any

from loguru import logger

from .base import BaseExtractor, ExtractionResult

try:
    import pytesseract  # type: ignore[import-untyped]
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


def _installed_languages() -> set[str]:
    """Return the languages actually installed for Tesseract (never assume)."""
    import subprocess
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True,
                             timeout=10, check=False).stdout
    except Exception:
        return set()
    lines = [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]
    return {ln for ln in lines if ln and not ln.startswith("List of")}


def resolve_languages(requested: str | None = None) -> str:
    """Intersect requested languages with the installed set (graceful fallback)."""
    requested = requested or ocr_languages()
    wanted = [x.strip() for x in requested.split("+") if x.strip()]
    installed = _installed_languages()
    if not installed:
        return requested
    available = [x for x in wanted if x in installed]
    if not available:
        fallback = [x for x in ("eng", "fra", "deu") if x in installed]
        return "+".join(fallback) if fallback else sorted(installed)[0]
    return "+".join(available)


def is_ocr_candidate(path: Path, *, pdf_had_text: bool = False, explicit: bool = False) -> bool:
    """Conservative OCR policy: image-only PDFs and explicitly requested images.

    Ordinary photos are not OCR'd by default.
    """
    suffix = path.suffix.lower()
    if suffix in PDF_EXTENSIONS:
        return not pdf_had_text
    if suffix in IMAGE_EXTENSIONS:
        return explicit
    return False


def ocr_max_pages() -> int:
    return max(1, _env_int("PIS_OCR_MAX_PAGES", 5))


def ocr_timeout() -> int:
    return max(1, _env_int("PIS_OCR_TIMEOUT", 30))


def ocr_max_bytes() -> int:
    return max(1, _env_int("PIS_OCR_MAX_BYTES", 25 * 1024 * 1024))


def tesseract_available() -> bool:
    return OCR_LIBS_AVAILABLE and shutil.which("tesseract") is not None


def _preprocess(image: Any) -> Any:
    """Grayscale + autocontrast; improves low-contrast scans without destroying text."""
    try:
        from PIL import ImageOps
        if image.mode not in ("L", "1"):
            image = image.convert("L")
        return ImageOps.autocontrast(image)
    except Exception:
        return image


def _fix_orientation(image: Any) -> Any:
    """Rotate using Tesseract OSD when the ``osd`` model is installed."""
    if "osd" not in _installed_languages():
        return image
    try:
        osd = pytesseract.image_to_osd(image)
        import re
        m = re.search(r"Rotate: (\d+)", osd)
        if m:
            angle = int(m.group(1)) % 360
            if angle:
                return image.rotate(-angle, expand=True)
    except Exception:
        pass
    return image


def _ocr_image_file(path: Path, langs: str) -> str:
    with Image.open(path) as image:
        image = _fix_orientation(image)
        image = _preprocess(image)
        return str(pytesseract.image_to_string(image, lang=langs, timeout=ocr_timeout()))


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
        from pdf2image import convert_from_path  # type: ignore[import-not-found]

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


def ocr_file(path: Path, *, langs: str | None = None) -> ExtractionResult:
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
        langs = resolve_languages(langs)
        if suffix in IMAGE_EXTENSIONS:
            text = _ocr_image_file(path, langs)
        else:
            with tempfile.TemporaryDirectory(prefix="pis-ocr-") as tmp:
                pages = _render_pdf_pages(path, Path(tmp), ocr_max_pages())
                text = "\n".join(_ocr_image_file(page, langs) for page in pages)
        text = text.strip()
        if not text:
            return ExtractionResult(success=False, error="no text recognised (OCR_FAILED)",
                                    extraction_time=time.time() - start)
        return ExtractionResult(success=True, content=text, metadata={"ocr": True, "langs": langs}, extraction_time=time.time() - start)
    except Exception as exc:  # noqa: BLE001 - failure isolation
        logger.debug(f"OCR failed for {path}: {exc}")
        return ExtractionResult(success=False, error=f"OCR error: {exc}", extraction_time=time.time() - start)


class OcrExtractor(BaseExtractor):
    """Extractor facade for images / scanned PDFs (disabled by default)."""

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.supported_extensions = IMAGE_EXTENSIONS | PDF_EXTENSIONS

    def can_extract(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions and file_path.is_file()

    def extract_content(self, file_path: Path) -> ExtractionResult:
        return ocr_file(file_path)
