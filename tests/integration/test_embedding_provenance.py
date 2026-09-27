"""Embedding store provenance isolation across providers (M012-A / M011)."""
from __future__ import annotations

import numpy as np

from src.ai.providers.adapters import ProviderEmbeddingGenerator
from src.intelligence.embedding_store import EmbeddingMatrixStore
from tests.ai_fakes import FakeEmbedding


def _local_store(tmp_path, key="bge-m3", name="BAAI/bge-m3", dim=8):
    return EmbeddingMatrixStore(key, name, dim, base_dir=tmp_path / "store")


def test_remote_adapter_provenance_is_namespaced(tmp_path):
    provider = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, dim=8)
    adapter = ProviderEmbeddingGenerator(provider)
    assert adapter.model_key == "openai_compatible_embeddings:emb-remote"
    assert adapter.model_name == "emb-remote"
    assert adapter.embedding_dim == 8
    vectors = adapter.generate_batch_embeddings(["a", "bb"])
    assert len(vectors) == 2 and vectors[0].shape == (8,)


def test_local_and_remote_stores_never_mix(tmp_path):
    local = _local_store(tmp_path)
    local.save([1, 2], np.ones((2, 8), dtype=np.float32))

    provider = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, dim=8)
    adapter = ProviderEmbeddingGenerator(provider)
    remote = EmbeddingMatrixStore(adapter.model_key, adapter.model_name, adapter.embedding_dim,
                                  base_dir=tmp_path / "store")

    assert remote.dir != local.dir
    assert not remote.exists(), "remote provider must not reuse the local store"
    # Even forcing the same directory must refuse the model mismatch.
    forced = EmbeddingMatrixStore("bge-m3", "BAAI/bge-m3", 8, base_dir=tmp_path / "store")
    assert forced.load() is True
    other = EmbeddingMatrixStore(adapter.model_key, adapter.model_name, 8, base_dir=tmp_path / "store")
    other.dir = forced.dir
    assert other.load() is False


def test_remote_adapter_dimension_mismatch_rejected(tmp_path):
    provider = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, dim=8)
    adapter = ProviderEmbeddingGenerator(provider)
    store = EmbeddingMatrixStore(adapter.model_key, adapter.model_name, 16, base_dir=tmp_path / "store")
    store.dir = (tmp_path / "store" / adapter.model_key)
    store.save([1], np.ones((1, 16), dtype=np.float32))
    mismatch = EmbeddingMatrixStore(adapter.model_key, adapter.model_name, 8, base_dir=tmp_path / "store")
    assert mismatch.load() is False
