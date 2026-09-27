"""Freshness contract for the embedding store + semantic layer (M010 scale).

Locks the M009I review fixes:

* changed content is re-embedded (content-hash compare), not left stale;
* rows whose document is deleted/MISSING are pruned and can never be returned;
* pruning compacts the matrix and survives a reload;
* legacy stores without content hashes refresh on first use.
"""
from __future__ import annotations

import numpy as np

from src.intelligence.embedding_store import EmbeddingMatrixStore


def _store(tmp_path, dim=8, key="fresh"):
    return EmbeddingMatrixStore(key, "test/model", dim, base_dir=tmp_path)


def test_content_hashes_persist_and_update(tmp_path) -> None:
    store = _store(tmp_path)
    matrix = np.random.default_rng(0).standard_normal((3, 8)).astype(np.float32)
    store.save([1, 2, 3], matrix, hashes=["a", "b", "c"])
    assert store.hash_map() == {1: "a", 2: "b", 3: "c"}

    store.append([2], np.random.default_rng(1).standard_normal((1, 8)).astype(np.float32), hashes=["b2"])
    assert store.hash_map()[2] == "b2"

    reloaded = _store(tmp_path)
    assert reloaded.load() is True
    assert reloaded.hash_map() == {1: "a", 2: "b2", 3: "c"}


def test_prune_removes_rows_and_compacts(tmp_path) -> None:
    store = _store(tmp_path)
    matrix = np.random.default_rng(2).standard_normal((5, 8)).astype(np.float32)
    store.save([10, 11, 12, 13, 14], matrix, hashes=["h10", "h11", "h12", "h13", "h14"])

    removed = store.prune({10, 12, 14})
    assert removed == 2
    assert store.meta.ids == [10, 12, 14]
    assert store.meta.count == 3
    assert store.hash_map() == {10: "h10", 12: "h12", 14: "h14"}
    # Remaining rows keep their original vectors (order of survivors preserved).
    assert np.allclose(store.matrix[0], EmbeddingMatrixStore.normalize(matrix[0]))
    assert np.allclose(store.matrix[1], EmbeddingMatrixStore.normalize(matrix[2]))

    reloaded = _store(tmp_path)
    assert reloaded.load() is True
    assert reloaded.meta.ids == [10, 12, 14]


def test_prune_all_empties_store(tmp_path) -> None:
    store = _store(tmp_path)
    store.save([1, 2], np.ones((2, 8), dtype=np.float32), hashes=["a", "b"])
    assert store.prune(set()) == 2
    assert store.meta.count == 0
    assert store.search(np.ones(8, dtype=np.float32), 5) == []


def test_legacy_v1_store_is_migrated(tmp_path) -> None:
    store = _store(tmp_path)
    store.save([1, 2], np.ones((2, 8), dtype=np.float32), hashes=["a", "b"])
    # Rewrite as a v1 meta.json (ids/hashes inline) and drop the sidecars.
    import json

    meta = json.loads((store.dir / "meta.json").read_text())
    meta.update({"version": 1, "ids": [1, 2], "content_hashes": ["a", "b"],
                 "capacity": store.meta.capacity})
    (store.dir / "meta.json").write_text(json.dumps(meta))
    (store.dir / "ids.npy").unlink()
    (store.dir / "hashes.npy").unlink()

    reloaded = _store(tmp_path)
    assert reloaded.load() is True
    assert reloaded.hash_map() == {1: "a", 2: "b"}
    assert (store.dir / "ids.npy").exists() and (store.dir / "hashes.npy").exists()


def test_legacy_store_without_hashes_migrates_to_unknown(tmp_path) -> None:
    store = _store(tmp_path)
    store.save([1, 2], np.ones((2, 8), dtype=np.float32))
    import json

    meta = json.loads((store.dir / "meta.json").read_text())
    meta.update({"version": 1, "ids": [1, 2], "capacity": store.meta.capacity})
    (store.dir / "meta.json").write_text(json.dumps(meta))
    (store.dir / "ids.npy").unlink()
    (store.dir / "hashes.npy").unlink()

    reloaded = _store(tmp_path)
    assert reloaded.load() is True
    assert reloaded.hash_map() == {}  # unknown -> caller re-embeds
