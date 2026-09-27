"""Canonical duplicate / version / related-document support (M014).

This package builds on the existing canonical layers (SQLite ``DatabaseManager``,
lifecycle, extraction, semantic_state/store, archive members) and adds:

* persistent content-hash metadata (exact identity),
* exact duplicate grouping,
* explainable near-duplicate discovery (bounded, non-quadratic),
* version-family tracking with explicit confidence,
* related-document suggestions,
* duplicate-aware reranking / fusion.

Nothing here mutates user files and no destructive action is ever taken.
"""
from __future__ import annotations

from .exact import ExactDuplicateEngine
from .hashing import (
    HASH_OK,
    HASH_SKIPPED,
    HASH_TOO_LARGE,
    HASH_UNREADABLE,
    ContentHasher,
)
from .near import NearDuplicateEngine
from .related import RelatedDocuments
from .rerank import fuse_results, rerank_search
from .store import DedupStore
from .versions import VersionTracker

__all__ = [
    "DedupStore",
    "ContentHasher",
    "ExactDuplicateEngine",
    "NearDuplicateEngine",
    "VersionTracker",
    "RelatedDocuments",
    "fuse_results",
    "rerank_search",
    "HASH_OK",
    "HASH_SKIPPED",
    "HASH_TOO_LARGE",
    "HASH_UNREADABLE",
]
