"""Tests for the persistent embedding matrix store (M009I.1)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from src.intelligence.embedding_store import EmbeddingMatrixStore, EmbeddingStoreError


def _store(tmp_path, dim=8, key="m1"):
    return EmbeddingMatrixStore(key, "test/model", dim, base_dir=tmp_path)


def test_save_load_normalized_and_deterministic(tmp_path):
    store = _store(tmp_path)
    matrix = np.random.default_rng(0).standard_normal((5, 8)).astype(np.float32)
    store.save([10, 11, 12, 13, 14], matrix)
    norms = np.linalg.norm(store.matrix, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)

    reloaded = _store(tmp_path)
    assert reloaded.load() is True
    assert reloaded.meta.ids == [10, 11, 12, 13, 14]
    assert reloaded.meta.normalized is True

    query = np.random.default_rng(1).standard_normal(8).astype(np.float32)
    a = store.search(query, 3)
    b = reloaded.search(query, 3)
    assert a == b


def test_search_matches_bruteforce(tmp_path):
    store = _store(tmp_path, dim=16)
    matrix = np.random.default_rng(3).standard_normal((50, 16)).astype(np.float32)
    ids = list(range(50))
    store.save(ids, matrix)
    q = np.random.default_rng(4).standard_normal(16).astype(np.float32)
    result = store.search(q, 5)

    norm_matrix = store.matrix
    scores = norm_matrix @ (q / np.linalg.norm(q))
    expected = sorted(zip(ids, scores.tolist()), key=lambda x: (-x[1], x[0]))[:5]
    assert [i for i, _ in result] == [i for i, _ in expected]
    for (_, a), (_, b) in zip(result, expected):
        assert abs(a - b) < 1e-5


def test_incremental_append_and_update(tmp_path):
    store = _store(tmp_path)
    matrix = np.random.default_rng(5).standard_normal((3, 8)).astype(np.float32)
    store.save([1, 2, 3], matrix)
    new = np.random.default_rng(6).standard_normal((2, 8)).astype(np.float32)
    store.append([4, 5], new)
    assert store.meta.ids == [1, 2, 3, 4, 5]

    replacement = np.random.default_rng(7).standard_normal((1, 8)).astype(np.float32)
    store.append([2], replacement)
    assert store.meta.count == 5  # replaced, not duplicated
    assert store.meta.ids.count(2) == 1


def test_model_and_dimension_mismatch_rejected(tmp_path):
    store = _store(tmp_path)
    store.save([1], np.ones((1, 8), dtype=np.float32))

    other_model = EmbeddingMatrixStore("m2", "other", 8, base_dir=tmp_path)
    other_model.dir = store.dir  # force same dir
    assert other_model.load() is False

    other_dim = EmbeddingMatrixStore("m1", "test/model", 16, base_dir=tmp_path)
    assert other_dim.load() is False

    with pytest.raises(EmbeddingStoreError):
        store.search(np.ones(4, dtype=np.float32), 1)


def test_corruption_detected(tmp_path):
    store = _store(tmp_path)
    store.save([1, 2], np.random.default_rng(8).standard_normal((2, 8)).astype(np.float32))
    meta = json.loads((store.dir / "meta.json").read_text())
    meta["count"] = 99  # inconsistent
    (store.dir / "meta.json").write_text(json.dumps(meta))
    assert _store(tmp_path).load() is False


def test_non_finite_rejected(tmp_path):
    store = _store(tmp_path)
    bad = np.ones((2, 8), dtype=np.float32)
    bad[0, 0] = np.inf
    store.save([1, 2], bad)
    # save normalizes inf -> nan; reload must reject
    assert _store(tmp_path).load() is False
