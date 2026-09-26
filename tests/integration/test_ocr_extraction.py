"""Optional Tesseract OCR fallback tests (M009H.7)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytesseract")
pytest.importorskip("PIL")

from PIL import Image, ImageDraw  # noqa: E402

from src.extractors import ocr  # noqa: E402
from src.extractors.manager import ExtractionManager  # noqa: E402


def _make_image(path: Path, text: str) -> None:
    image = Image.new("RGB", (700, 120), "white")
    ImageDraw.Draw(image).text((10, 40), text, fill="black")
    image.save(path)


def test_disabled_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PIS_OCR_ENABLED", raising=False)
    image = tmp_path / "scan.png"
    _make_image(image, "Hello World")
    assert ocr.ocr_enabled() is False
    result = ocr.OcrExtractor().extract_content(image)
    assert result.success is False
    assert "disabled" in (result.error or "")
    # Manager must not claim a suitable extractor when OCR is off.
    assert ExtractionManager().extract_single(image).success is False


def test_enabled_extracts_text(tmp_path: Path, monkeypatch) -> None:
    if not ocr.tesseract_available():
        pytest.skip("tesseract not available")
    monkeypatch.setenv("PIS_OCR_ENABLED", "1")
    monkeypatch.setenv("PIS_OCR_LANGS", "eng")
    image = tmp_path / "scan2.png"
    _make_image(image, "Invoice Total 15000 EUR")
    result = ExtractionManager().extract_single(image)
    assert result.success
    assert "15000" in result.content or "Invoice" in result.content


def test_malformed_image_is_isolated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_OCR_ENABLED", "1")
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    result = ocr.ocr_file(broken)
    assert result.success is False
    assert result.error


def test_size_limit_is_enforced(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_OCR_ENABLED", "1")
    monkeypatch.setenv("PIS_OCR_MAX_BYTES", "1")
    image = tmp_path / "big.png"
    _make_image(image, "x")
    result = ocr.ocr_file(image)
    assert result.success is False
    assert "size limit" in (result.error or "")
