"""Performance-lock tests: extraction/OCR worker defaults (M010-P.1).

Extraction is GIL/CPU-bound and measured fastest single-worker on a
representative mixed corpus (2 workers -5%, 4 workers -13%); full-page OCR peaks
at 8 workers (16/24 are slower and inflate per-page latency). These tests lock
those defaults so a future change cannot silently regress them.
"""
from __future__ import annotations

from src.core.perf_config import get_resource_config, reset_resource_config
from src.extractors.manager import ExtractionManager


def test_extraction_defaults_to_single_worker(monkeypatch) -> None:
    monkeypatch.delenv("PIS_EXTRACT_WORKERS", raising=False)
    reset_resource_config()
    assert ExtractionManager().max_workers == 1
    assert get_resource_config().extract_workers == 1
    reset_resource_config()


def test_ocr_defaults_to_eight_workers(monkeypatch) -> None:
    monkeypatch.delenv("PIS_OCR_WORKERS", raising=False)
    reset_resource_config()
    assert get_resource_config().ocr_workers == 8
    reset_resource_config()


def test_extract_workers_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PIS_EXTRACT_WORKERS", "4")
    reset_resource_config()
    assert get_resource_config().extract_workers == 4
    reset_resource_config()
