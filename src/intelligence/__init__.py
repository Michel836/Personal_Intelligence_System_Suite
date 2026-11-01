"""AI intelligence modules for semantic search and analysis.

Heavy backends (``torch``/``sentence-transformers``/``ollama``) are imported
lazily. Importing this package -- or a lightweight submodule such as
``src.intelligence.embedding_job`` -- must never pull the ML stack into a LITE
startup. Attribute access keeps the historical public API working::

    from src.intelligence import EmbeddingGenerator
"""
from __future__ import annotations

from typing import Any

__all__ = ["EmbeddingGenerator", "SemanticSearchEngine", "ChatEngine"]


def __getattr__(name: str) -> Any:
    if name == "EmbeddingGenerator":
        from .embeddings import EmbeddingGenerator

        return EmbeddingGenerator
    if name == "SemanticSearchEngine":
        from .semantic_search import SemanticSearchEngine

        return SemanticSearchEngine
    if name == "ChatEngine":
        from .chat_engine import ChatEngine

        return ChatEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
