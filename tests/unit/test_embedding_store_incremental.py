"""Incremental-store contract tests for EmbeddingMatrixStore (M010-P).

The append path used to rewrite the whole matrix (O(n)); these tests lock the
observable contract (ids, count, search equivalence, restart safety, corruption
detection) independently of the on-disk capacity strategy.
"""
from __future__ import annotations

import json

import numpy as np

from src.intelligence.embedding_store import EmbeddingMatrixStore, EmbeddingStoreError


def _store(tmp_path, dim=8, key="inc"):
    return EmbeddingMatrixStore(key, "test/model", dim, base_dir=tmp_path)


def test_repeated_small_appends_preserve_ids_and_search(tmp_path) -> None:
    store = _store(tmp_path, dim=16)
    first = np.random.default_rng(0).standard_normal((5, 16)).astype(np.float32)
    store.save([0, 1, 2, 3, 4], first)
    for step in range(1, 6):
        rows = np.random.default_rng(step).standard_normal((3, 16)).astype(np.float32)
        store.append([step * 10 + i for i in range(3)], rows)
    assert store.meta.count == 20
    assert len(set(store.meta.ids)) == 20

    reloaded = _store(tmp_path, dim=16)
    assert reloaded.load() is True
    query = np.random.default_rng(99).standard_normal(16).astype(np.float32)
    assert store.search(query, 5) == reloaded.search(query, 5)


def test_append_replaces_without_duplication(tmp_path) -> None:
    store = _store(tmp_path, dim=4)
    store.save([1, 2, 3], np.ones((3, 4), dtype=np.float32))
    replacement = np.zeros((1, 4), dtype=np.float32)
    replacement[0, 0] = 1.0
    store.append([2], replacement)
    assert store.meta.count == 3
    assert store.meta.ids.count(2) == 1
    # The replaced row is the new vector, not the old one.
    assert np.allclose(store.matrix[store.meta.ids.index(2)], replacement[0])


def test_capacity_growth_is_reloadable(tmp_path) -> None:
    store = _store(tmp_path, dim=4)
    store.save([1], np.ones((1, 4), dtype=np.float32))
    # Force several geometric growths.
    for i in range(2, 300):
        store.append([i], np.full((1, 4), float(i % 7), dtype=np.float32))
    reloaded = _store(tmp_path, dim=4)
    assert reloaded.load() is True
    assert reloaded.meta.count == 299
    assert np.isfinite(reloaded.matrix).all()


def test_unreadable_matrix_is_rejected(tmp_path) -> None:
    store = _store(tmp_path, dim=4)
    store.save([1, 2], np.ones((2, 4), dtype=np.float32))
    # Corrupt the declared capacity beyond the actual matrix shape.
    meta = json.loads((store.dir / "meta.json").read_text())
    meta["capacity"] = 10_000
    (store.dir / "meta.json").write_text(json.dumps(meta))
    assert _store(tmp_path, dim=4).load() is False


def test_dimension_mismatch_on_append_rejected(tmp_path) -> None:
    store = _store(tmp_path, dim=4)
    store.save([1], np.ones((1, 4), dtype=np.float32))
    try:
        store.append([2], np.ones((1, 5), dtype=np.float32))
    except EmbeddingStoreError:
        return
    raise AssertionError("expected EmbeddingStoreError")
