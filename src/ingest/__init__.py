"""M017 ingestion: email/legacy/EPUB/CHM extraction, outcome taxonomy,
retry queue, OCR policy and email threading.

Local-only. No cloud conversion, no destructive source modification, no
mandatory external service. Extracted text flows through the canonical
``update_content`` path so FTS, semantic state, language/entities/categories/PII
and the graph all see it.
"""
from __future__ import annotations

from typing import Any

from .capabilities import capability_matrix
from .cfb import CfbError, read_cfb_streams
from .queue_store import ExtractionQueue
from .taxonomy import (
    MAX_ATTEMPTS,
    Outcome,
    backoff_seconds,
    classify_error,
    is_retryable,
    is_terminal,
)
from .thread_store import EmailThreadStore

__all__ = [
    "IngestionPipeline", "ExtractionQueue", "EmailThreadStore", "Outcome",
    "classify_error", "is_terminal", "is_retryable", "backoff_seconds", "MAX_ATTEMPTS",
    "capability_matrix", "read_cfb_streams", "CfbError",
]


def __getattr__(name: str) -> Any:
    # Lazy to avoid an import cycle: extractors import ``src.ingest.tools``,
    # while the pipeline imports the extractor manager.
    if name == "IngestionPipeline":
        from .pipeline import IngestionPipeline
        return IngestionPipeline
    raise AttributeError(name)
