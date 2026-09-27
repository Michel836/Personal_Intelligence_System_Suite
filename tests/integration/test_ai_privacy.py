"""Privacy acceptance: LOCAL/never never calls a remote provider (M012-A)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

import src.intelligence.semantic_search as ss
from src.ai.providers.policy import RemoteContentPolicy
from src.ai.providers.service import AIService
from src.core.database import DatabaseManager
from src.intelligence.chat_engine import ChatEngine
from src.intelligence.semantic_search import SemanticSearchEngine
from tests.ai_fakes import FakeEmbedding, FakeLLM, make_config, make_router, profile

BODY = "BODYSECRETTOKEN"


class _NullEmbeddings:
    """Legacy EmbeddingGenerator interface that never loads a model."""

    model_key = "null-local"
    model_name = "null-local"
    embedding_dim = 4

    def is_available(self) -> bool:
        return False

    def generate_embedding(self, text):
        return None

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        return [None] * len(texts)

    def load_embedding_cache(self, key):
        return None

    def save_embedding_cache(self, key, embedding):
        return None


def _install(monkeypatch, service):
    monkeypatch.setattr("src.ai.providers.service.get_ai_service", lambda *a, **k: service)
    monkeypatch.setattr(ss, "EmbeddingGenerator", _NullEmbeddings)

    def no_remote_http(*a, **k):  # pragma: no cover - only fires on violation
        raise AssertionError("remote HTTP call attempted")

    monkeypatch.setattr("requests.Session.post", no_remote_http)


def _service(config, llm_providers, emb_providers=None, **profile_kw):
    router = make_router(config, llm_providers=llm_providers,
                         emb_providers=emb_providers or {}, hardware_profile=profile(**profile_kw))
    return AIService(config, router=router)


def _doc():
    return {"id": 1, "filename": "a.txt", "path": "/corpus/a.txt", "file_type": "document",
            "size_bytes": 10, "content_text": f"{BODY} extracted body text"}


def _engine(tmp_path, monkeypatch, service, name):
    _install(monkeypatch, service)
    db = DatabaseManager(tmp_path / f"{name}.db")
    engine = ChatEngine(db=db)
    engine._search_relevant_documents = lambda query, max_docs=5: [_doc()]
    return engine


def test_local_mode_zero_remote_calls(tmp_path, monkeypatch):
    remote = FakeLLM("openai_compatible", "gpt", remote=True)
    local = FakeLLM("ollama", "qwen-local", remote=False)
    cfg = make_config(mode="local", api_base_url="https://api.example/v1", api_key="sk-x",
                      api_llm_model="gpt", content_policy=RemoteContentPolicy.FULL_CONTEXT)
    engine = _engine(tmp_path, monkeypatch, _service(cfg, {"ollama": local, "openai_compatible": remote}), "local")
    out = engine.chat("question", search_context=True)
    assert remote.calls == 0
    assert local.calls == 1
    assert out["provider"] == "ollama"


def test_never_policy_blocks_remote_in_api_mode(tmp_path, monkeypatch):
    remote = FakeLLM("openai_compatible", "gpt", remote=True)
    local = FakeLLM("ollama", "qwen-local", remote=False)
    cfg = make_config(mode="api", api_base_url="https://api.example/v1", api_key="sk-x",
                      api_llm_model="gpt", content_policy=RemoteContentPolicy.NEVER)
    engine = _engine(tmp_path, monkeypatch, _service(cfg, {"ollama": local, "openai_compatible": remote}), "never")
    engine.chat("question", search_context=True)
    assert remote.calls == 0
    assert local.calls == 1


def test_metadata_only_omits_body_text(tmp_path, monkeypatch):
    remote = FakeLLM("openai_compatible", "gpt", remote=True)
    cfg = make_config(mode="api", api_base_url="https://api.example/v1", api_key="sk-x",
                      api_llm_model="gpt", content_policy=RemoteContentPolicy.METADATA_ONLY)
    engine = _engine(tmp_path, monkeypatch, _service(cfg, {"openai_compatible": remote}), "meta")
    out = engine.chat("question", search_context=True)
    assert out["provider"] == "openai_compatible"
    sent = " ".join(m["content"] for m in remote.last_messages)
    assert BODY not in sent, "metadata-only must not transmit extracted body text"
    assert "a.txt" in sent  # metadata is allowed


def test_extracted_text_policy_allows_body_excerpt(tmp_path, monkeypatch):
    remote = FakeLLM("openai_compatible", "gpt", remote=True)
    cfg = make_config(mode="api", api_base_url="https://api.example/v1", api_key="sk-x",
                      api_llm_model="gpt", content_policy=RemoteContentPolicy.EXTRACTED_TEXT)
    engine = _engine(tmp_path, monkeypatch, _service(cfg, {"openai_compatible": remote}), "text")
    out = engine.chat("question", search_context=True)
    assert out["provider"] == "openai_compatible"
    sent = " ".join(m["content"] for m in remote.last_messages)
    assert BODY in sent


def test_remote_embedding_selection_follows_policy(monkeypatch, tmp_path):
    remote_emb = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, dim=8)
    local_emb = FakeEmbedding("sentence_transformers", "bge-m3", remote=False, dim=8)
    base = dict(mode="api", api_base_url="https://api.example/v1", api_key="sk-x",
                api_embedding_model="emb-remote")

    never = _service(make_config(content_policy=RemoteContentPolicy.NEVER, **base),
                     {"openai_compatible": FakeLLM("openai_compatible", remote=True)},
                     {"sentence_transformers": local_emb, "openai_compatible": remote_emb})
    assert never.remote_embedding_generator() is None

    metadata = _service(make_config(content_policy=RemoteContentPolicy.METADATA_ONLY, **base),
                        {"openai_compatible": FakeLLM("openai_compatible", remote=True)},
                        {"sentence_transformers": local_emb, "openai_compatible": remote_emb})
    assert metadata.remote_embedding_generator() is None

    extracted = _service(make_config(content_policy=RemoteContentPolicy.EXTRACTED_TEXT, **base),
                         {"openai_compatible": FakeLLM("openai_compatible", remote=True)},
                         {"sentence_transformers": local_emb, "openai_compatible": remote_emb})
    generator = extracted.remote_embedding_generator()
    assert generator is not None
    assert generator.model_key == "openai_compatible_embeddings:emb-remote"


def test_semantic_engine_uses_local_store_under_never(tmp_path, monkeypatch):
    remote_emb = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, dim=8)
    cfg = make_config(mode="api", api_base_url="https://api.example/v1", api_key="sk-x",
                      api_embedding_model="emb-remote", content_policy=RemoteContentPolicy.NEVER)
    service = _service(cfg, {"openai_compatible": FakeLLM("openai_compatible", remote=True)},
                       {"sentence_transformers": _NullEmbeddings(), "openai_compatible": remote_emb})
    _install(monkeypatch, service)
    engine = SemanticSearchEngine(DatabaseManager(tmp_path / "sem.db"))
    # Local path preserved: the semantic engine keeps its own local generator.
    assert engine.embedding_gen.model_key == "null-local"
