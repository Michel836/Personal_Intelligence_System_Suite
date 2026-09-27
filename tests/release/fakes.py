"""Deterministic, fully local embedding fake for release acceptance.

Implements the small surface ``SemanticSearchEngine`` expects from
``EmbeddingGenerator`` using a hashing bag-of-words vector. It never loads a
model, never touches the network and gives meaningful cosine neighbourhoods for
lexical overlap, so semantic search/refresh can be exercised deterministically.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", re.UNICODE)


class HashingEmbeddingGenerator:
    def __init__(self, dim: int = 64) -> None:
        self.model_key = "release-hash"
        self.model_name = "release-hash-embedding"
        self.embedding_dim = int(dim)
        self.model = None
        self.calls = 0
        self._cache: dict[str, np.ndarray] = {}

    def is_available(self) -> bool:
        return True

    def _vec(self, text: str) -> np.ndarray:
        vec = np.zeros(self.embedding_dim, dtype=np.float32)
        for token in _TOKEN_RE.findall((text or "").lower()):
            vec[hash_token(token, self.embedding_dim)] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec

    def generate_embedding(self, text: str) -> np.ndarray:
        self.calls += 1
        return self._vec(text)

    def generate_batch_embeddings(self, texts: list[str], batch_size: int | None = None,
                                  show_progress: bool = False) -> list[np.ndarray]:
        _ = (batch_size, show_progress)
        self.calls += len(texts)
        return [self._vec(t) for t in texts]

    def find_similar(self, query: np.ndarray, doc_embeddings: list[np.ndarray],
                    top_k: int = 10) -> list[tuple[int, float]]:
        if not doc_embeddings:
            return []
        matrix = np.vstack(doc_embeddings)
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        qn = float(np.linalg.norm(q)) or 1.0
        scores = (matrix @ (q / qn)).astype(float)
        order = np.argsort(-scores)[: max(0, int(top_k))]
        return [(int(i), float(scores[int(i)])) for i in order]

    def load_embedding_cache(self, key: str) -> np.ndarray | None:
        return self._cache.get(key)

    def save_embedding_cache(self, key: str, embedding: np.ndarray) -> None:
        self._cache[key] = np.asarray(embedding, dtype=np.float32)

    def meta(self) -> dict[str, Any]:
        return {"model_key": self.model_key, "model_name": self.model_name,
                "dim": self.embedding_dim}


def hash_token(token: str, dim: int) -> int:
    """Stable, cross-run token -> dimension mapping (no PYTHONHASHSEED effect)."""
    value = 0
    for char in token:
        value = (value * 131 + ord(char)) & 0xFFFFFFFF
    return value % max(1, int(dim))


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a)) or 1.0
    nb = float(np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / (na * nb))
