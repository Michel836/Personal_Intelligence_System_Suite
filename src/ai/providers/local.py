"""Local SentenceTransformer embedding provider.

Wraps the existing, proven ``EmbeddingGenerator`` so the local bge-m3 path and
the M011 embedding store behave exactly as before. Exposes the underlying
generator so the semantic engine can keep using it directly (store provenance
unchanged).
"""
from __future__ import annotations

from typing import Optional, Sequence

from .base import EmbeddingProvider, EmbeddingResult, ModelInfo


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    name = "sentence_transformers"
    backend = "sentence_transformers"
    remote = False

    def __init__(self, model: Optional[str] = None, generator=None):
        if generator is None:
            from ...intelligence.embeddings import EmbeddingGenerator

            generator = EmbeddingGenerator(model)
        self._generator = generator
        self.model = getattr(generator, "model_name", model or "")

    @property
    def generator(self):
        """The underlying ``EmbeddingGenerator`` (store-compatible interface)."""
        return self._generator

    def is_available(self) -> bool:
        try:
            return bool(self._generator.is_available())
        except Exception:  # noqa: BLE001
            return False

    def dimension(self) -> int:
        return int(getattr(self._generator, "embedding_dim", 0) or 0)

    def model_info(self) -> ModelInfo:
        return ModelInfo(provider=self.name, model=self.model, remote=False,
                         dimension=self.dimension() or None)

    def embed_batch(self, texts: Sequence[str], *, batch_size: Optional[int] = None) -> EmbeddingResult:
        vectors = self._generator.generate_batch_embeddings(
            list(texts), batch_size=batch_size or 32, show_progress=False
        )
        out = [v.tolist() if v is not None else [] for v in vectors]
        return EmbeddingResult(vectors=out, provider=self.name, model=self.model,
                               dim=self.dimension())
