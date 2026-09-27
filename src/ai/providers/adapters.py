"""Legacy-interface adapters over provider contracts (M012-A).

``ProviderEmbeddingGenerator`` presents the ``EmbeddingGenerator`` API used by
``SemanticSearchEngine`` (model_key / model_name / embedding_dim /
generate_embedding / generate_batch_embeddings) on top of any
:class:`EmbeddingProvider`. It is used only for remote providers; the local
SentenceTransformer path keeps using the real ``EmbeddingGenerator`` directly so
its store provenance and behaviour are unchanged.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from .base import EmbeddingProvider


class ProviderEmbeddingGenerator:
    name = "provider_embedding_generator"

    def __init__(self, provider: EmbeddingProvider, *, model_key: Optional[str] = None):
        self._provider = provider
        info = provider.model_info()
        self.model_key = model_key or f"{info.provider}:{info.model}"
        self.model_name = info.model
        self._dim = int(provider.dimension() or 0)

    @property
    def embedding_dim(self) -> int:
        if not self._dim:
            self._dim = int(self._provider.dimension() or 0)
        return self._dim

    def is_available(self) -> bool:
        try:
            return bool(self._provider.is_available())
        except Exception:  # noqa: BLE001
            return False

    def generate_embedding(self, text: str) -> Optional[np.ndarray]:
        result = self._provider.embed(text)
        if not result.vectors or not result.vectors[0]:
            return None
        self._dim = result.dim
        return np.asarray(result.vectors[0], dtype=np.float32)

    def generate_batch_embeddings(
        self, texts: Sequence[str], batch_size: int = 32, show_progress: bool = True
    ) -> list[Optional[np.ndarray]]:
        result = self._provider.embed_batch(list(texts), batch_size=batch_size)
        if result.dim:
            self._dim = result.dim
        out: list[Optional[np.ndarray]] = []
        for vector in result.vectors:
            out.append(np.asarray(vector, dtype=np.float32) if vector else None)
        return out

    def get_model_info(self) -> dict:
        info = self._provider.model_info()
        return {
            "provider": info.provider,
            "model_name": info.model,
            "remote": info.remote,
            "available": self.is_available(),
            "embedding_dimension": info.dimension or self._dim,
        }

    # Cache hooks are no-ops for providers (the semantic store owns persistence).
    def load_embedding_cache(self, key: str) -> Optional[np.ndarray]:
        return None

    def save_embedding_cache(self, key: str, embedding: np.ndarray) -> None:
        return None
