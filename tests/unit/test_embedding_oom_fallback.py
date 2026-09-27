"""Adaptive CUDA-OOM fallback for the local embedding generator (M013-C2).

No real GPU is required: a fake model raises the canonical CUDA OOM message
above a batch-size threshold, so the deterministic fallback ladder is exercised.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.intelligence.embeddings import EmbeddingGenerationError, EmbeddingGenerator


class FakeModel:
    """OOM when asked to encode more than ``fail_over`` texts at once."""

    def __init__(self, fail_over: int, dim: int = 4, hard_error: bool = False):
        self.fail_over = fail_over
        self.dim = dim
        self.hard_error = hard_error
        self.calls: list[int] = []

    def encode(self, texts, batch_size=None):  # noqa: ANN001
        # Real encoders chunk internally by ``batch_size``; emulate that so the
        # OOM depends on the requested batch, not the full input length.
        effective = batch_size if batch_size is not None else len(texts)
        self.calls.append(effective)
        if self.hard_error:
            raise ValueError("unrelated model error")
        if effective > self.fail_over:
            raise RuntimeError(
                "CUDA out of memory. Tried to allocate 5.5 GiB. "
                "GPU 0 has a total capacity of 23.5 GiB of which 762 MiB is free."
            )
        return np.ones((len(texts), self.dim), dtype=np.float32)


def _generator(tmp_path: Path, model: FakeModel) -> EmbeddingGenerator:
    gen = EmbeddingGenerator.__new__(EmbeddingGenerator)
    gen.model = model
    gen.model_key = "fake"
    gen.model_name = "fake/model"
    gen.embedding_dim = model.dim
    gen.cache_dir = tmp_path
    gen.last_effective_batch_size = None
    return gen


def test_oom_halves_batch_and_preserves_all_vectors(tmp_path: Path) -> None:
    model = FakeModel(fail_over=2)
    gen = _generator(tmp_path, model)
    texts = [f"text {i}" for i in range(16)]

    out = gen.generate_batch_embeddings(texts, batch_size=16, show_progress=False)

    assert len(out) == 16
    assert all(v is not None and v.shape == (4,) for v in out)
    # It tried the large batch first, then stepped the ladder down to <= 2.
    assert model.calls[0] == 16
    assert max(model.calls) == 16
    assert gen.last_effective_batch_size == 2
    assert model.calls == [16, 8, 4, 2]


def test_failure_is_explicit_at_minimum_batch(tmp_path: Path) -> None:
    model = FakeModel(fail_over=0)
    gen = _generator(tmp_path, model)

    with pytest.raises(EmbeddingGenerationError):
        gen.generate_batch_embeddings(["a", "b"], batch_size=2, show_progress=False)

    # Bounded: 2 then 1, and it stops explicitly.
    assert model.calls == [2, 1]


def test_non_oom_errors_propagate(tmp_path: Path) -> None:
    gen = _generator(tmp_path, FakeModel(fail_over=8, hard_error=True))
    with pytest.raises(ValueError):
        gen.generate_batch_embeddings(["a"], batch_size=8, show_progress=False)


def test_single_embedding_returns_none_on_failure(tmp_path: Path) -> None:
    gen = _generator(tmp_path, FakeModel(fail_over=0))
    assert gen.generate_embedding("hello") is None


def test_no_oom_path_uses_requested_batch(tmp_path: Path) -> None:
    model = FakeModel(fail_over=1024)
    gen = _generator(tmp_path, model)
    out = gen.generate_batch_embeddings(["a", "b", "c"], batch_size=3, show_progress=False)
    assert all(v is not None for v in out)
    assert gen.last_effective_batch_size == 3


def test_is_cuda_oom_classifier() -> None:
    assert EmbeddingGenerator._is_cuda_oom(RuntimeError("CUDA out of memory. Tried to allocate"))
    assert EmbeddingGenerator._is_cuda_oom(RuntimeError("out of memory"))
    assert not EmbeddingGenerator._is_cuda_oom(ValueError("invalid input"))
    assert not EmbeddingGenerator._is_cuda_oom(RuntimeError("connection reset"))
