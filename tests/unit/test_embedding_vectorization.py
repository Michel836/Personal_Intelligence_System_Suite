"""Regression tests for the vectorized EmbeddingGenerator.find_similar (M009H.1)."""
from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.embeddings import EmbeddingGenerator


def _reference(query, candidates, top_k):
    """Original per-pair loop semantics."""
    similarities = []
    for i, candidate in enumerate(candidates):
        if candidate is None:
            continue
        n1 = np.linalg.norm(query)
        n2 = np.linalg.norm(candidate)
        sim = float(np.dot(query, candidate) / (n1 * n2)) if n1 and n2 else 0.0
        similarities.append((i, sim))
    similarities.sort(key=lambda x: x[1], reverse=True)
    return similarities[:top_k]


def test_matches_reference_within_tolerance():
    rng = np.random.default_rng(0)
    candidates = [rng.standard_normal(64).astype(np.float32) for _ in range(500)]
    candidates[7] = None
    query = rng.standard_normal(64).astype(np.float32)

    expected = _reference(query, candidates, 10)
    actual = EmbeddingGenerator.find_similar(None, query, candidates, 10)

    assert [i for i, _ in actual] == [i for i, _ in expected]
    for (_, a), (_, b) in zip(actual, expected):
        assert abs(a - b) < 1e-5


def test_deterministic_tie_break_by_index():
    query = np.array([1.0, 0.0], dtype=np.float32)
    candidates = [np.array([1.0, 0.0], dtype=np.float32) for _ in range(5)]
    result = EmbeddingGenerator.find_similar(None, query, candidates, 3)
    assert [i for i, _ in result] == [0, 1, 2]


def test_empty_and_none():
    query = np.array([1.0, 0.0], dtype=np.float32)
    assert EmbeddingGenerator.find_similar(None, query, [], 5) == []
    assert EmbeddingGenerator.find_similar(None, query, [None, None], 5) == []
    assert EmbeddingGenerator.find_similar(None, None, [query], 5) == []
    assert EmbeddingGenerator.find_similar(None, query, [query], 0) == []


def test_top_k_clamped_to_corpus_size():
    query = np.array([1.0, 0.0], dtype=np.float32)
    candidates = [np.array([1.0, 0.0], dtype=np.float32), np.array([0.0, 1.0], dtype=np.float32)]
    assert len(EmbeddingGenerator.find_similar(None, query, candidates, 10)) == 2


def test_matrix_fast_path_matches_list():
    rng = np.random.default_rng(2)
    matrix = rng.standard_normal((200, 32)).astype(np.float32)
    query = rng.standard_normal(32).astype(np.float32)
    as_matrix = EmbeddingGenerator.find_similar(None, query, matrix, 10)
    as_list = EmbeddingGenerator.find_similar(None, query, [row for row in matrix], 10)
    assert as_matrix == as_list


def test_empty_matrix_fast_path():
    query = np.zeros(4, dtype=np.float32)
    assert EmbeddingGenerator.find_similar(None, query, np.zeros((0, 4), dtype=np.float32), 5) == []


def test_dimension_mismatch_raises():
    query = np.array([1.0, 0.0], dtype=np.float32)
    candidates = [np.array([1.0, 0.0, 0.0], dtype=np.float32)]
    with pytest.raises(ValueError):
        EmbeddingGenerator.find_similar(None, query, candidates, 5)
