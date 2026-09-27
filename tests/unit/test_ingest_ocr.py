"""OCR hardening + candidate policy tests (M017)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.extractors import ocr
from src.extractors.ocr import is_ocr_candidate, resolve_languages


def test_ocr_candidate_policy(tmp_path) -> None:
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF")
    img = tmp_path / "photo.png"
    img.write_bytes(b"x")
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    assert is_ocr_candidate(pdf, pdf_had_text=False) is True
    assert is_ocr_candidate(pdf, pdf_had_text=True) is False
    assert is_ocr_candidate(img, explicit=False) is False   # ordinary image not OCR'd
    assert is_ocr_candidate(img, explicit=True) is True
    assert is_ocr_candidate(txt) is False


def test_resolve_languages_never_assumes() -> None:
    installed = ocr._installed_languages()
    resolved = resolve_languages("fra+deu+eng")
    assert resolved
    if installed:
        assert all(lang in installed for lang in resolved.split("+"))
    # bogus languages fall back to installed, never crash
    assert resolve_languages("zzz+yyy")


def test_ocr_synthetic_image() -> None:
    if not ocr.tesseract_available():
        pytest.skip("tesseract unavailable")
    try:
        from PIL import Image, ImageDraw
    except Exception:
        pytest.skip("Pillow unavailable")
    os.environ["PIS_OCR_ENABLED"] = "1"
    d = Path(tempfile.mkdtemp())
    img = Image.new("RGB", (500, 90), "white")
    ImageDraw.Draw(img).text((10, 35), "HELLO OCR 2026", fill="black")
    p = d / "t.png"
    img.save(p)
    res = ocr.ocr_file(p)
    assert res.success and res.content
    assert "OCR" in res.content.upper() or "HELLO" in res.content.upper()


def test_ocr_disabled_returns_explicit_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PIS_OCR_ENABLED", "0")
    p = tmp_path / "x.png"
    p.write_bytes(b"x")
    res = ocr.ocr_file(p)
    assert not res.success and "disabled" in (res.error or "").lower()
