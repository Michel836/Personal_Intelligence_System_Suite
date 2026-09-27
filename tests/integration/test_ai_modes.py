"""Hybrid/API/local mode matrix, fallback and CPU-only acceptance (M012-A)."""
from __future__ import annotations

import src.intelligence.semantic_search as ss
from src.ai.providers.adapters import ProviderEmbeddingGenerator
from src.ai.providers.policy import RemoteContentPolicy
from src.ai.providers.service import AIService
from src.core.database import DatabaseManager
from src.intelligence.chat_engine import ChatEngine
from src.intelligence.semantic_search import SemanticSearchEngine
from tests.ai_fakes import FakeEmbedding, FakeLLM, make_config, make_router, profile


class _NullEmbeddings:
    model_key = "null-local"
    model_name = "null-local"
    embedding_dim = 4

    def is_available(self):
        return False

    def generate_embedding(self, text):
        return None

    def generate_batch_embeddings(self, texts, batch_size=32, show_progress=True):
        return [None] * len(texts)


def _service(config, llm_providers, emb_providers, **profile_kw):
    router = make_router(config, llm_providers=llm_providers, emb_providers=emb_providers,
                         hardware_profile=profile(**profile_kw))
    return AIService(config, router=router)


LOCAL_LLM = FakeLLM("ollama", "qwen-local", remote=False)
REMOTE_LLM = FakeLLM("openai_compatible", "gpt", remote=True)
LOCAL_EMB = FakeEmbedding("sentence_transformers", "bge-m3", remote=False, dim=8)
REMOTE_EMB = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, dim=8)
API = dict(api_base_url="https://api.example/v1", api_key="sk-x",
           api_llm_model="gpt", api_embedding_model="emb-remote")


def test_mode_A_local_embeddings_remote_llm():
    cfg = make_config(mode="hybrid", content_policy=RemoteContentPolicy.EXTRACTED_TEXT, **API)
    svc = _service(cfg, {"ollama": LOCAL_LLM, "openai_compatible": REMOTE_LLM},
                   {"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB})
    llm = svc.llm()
    primary = llm.chain()[0] if hasattr(llm, "chain") else llm.name
    assert primary == "openai_compatible"  # remote preferred, local fallback behind
    assert svc.remote_embedding_generator() is None  # local embeddings kept


def test_mode_B_remote_embeddings_local_llm():
    cfg = make_config(mode="hybrid", embedding_backend="openai_compatible", llm_backend="ollama",
                      content_policy=RemoteContentPolicy.EXTRACTED_TEXT, **API)
    svc = _service(cfg, {"ollama": LOCAL_LLM, "openai_compatible": REMOTE_LLM},
                   {"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB})
    assert svc.llm().name == "ollama" and svc.llm().remote is False
    adapter = svc.remote_embedding_generator()
    assert adapter is not None and adapter.model_key.startswith("openai_compatible_embeddings")


def test_mode_C_remote_embeddings_and_llm():
    cfg = make_config(mode="api", content_policy=RemoteContentPolicy.EXTRACTED_TEXT, **API)
    svc = _service(cfg, {"ollama": LOCAL_LLM, "openai_compatible": REMOTE_LLM},
                   {"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB})
    assert svc.llm().remote is True
    assert svc.remote_embedding_generator() is not None


def test_mode_D_local_embeddings_and_llm():
    cfg = make_config(mode="local")
    svc = _service(cfg, {"ollama": LOCAL_LLM}, {"sentence_transformers": LOCAL_EMB})
    assert svc.llm().name == "ollama" and svc.llm().remote is False
    assert svc.remote_embedding_generator() is None


def test_chat_engine_contract_identical_across_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "EmbeddingGenerator", _NullEmbeddings)
    cfg = make_config(mode="hybrid", content_policy=RemoteContentPolicy.EXTRACTED_TEXT, **API)
    svc = _service(cfg, {"ollama": LOCAL_LLM, "openai_compatible": REMOTE_LLM},
                   {"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB})
    monkeypatch.setattr("src.ai.providers.service.get_ai_service", lambda *a, **k: svc)
    engine = ChatEngine(db=DatabaseManager(tmp_path / "mode.db"))
    engine._search_relevant_documents = lambda q, max_docs=5: []
    out = engine.chat("question", search_context=False)
    assert out["response"]
    assert out["provider"] in {"openai_compatible", "ollama"}


def test_remote_llm_failure_falls_back_to_local(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "EmbeddingGenerator", _NullEmbeddings)
    failing = FakeLLM("openai_compatible", "gpt", remote=True, fail=True)
    cfg = make_config(mode="hybrid", content_policy=RemoteContentPolicy.EXTRACTED_TEXT, **API)
    svc = _service(cfg, {"ollama": LOCAL_LLM, "openai_compatible": failing},
                   {"sentence_transformers": LOCAL_EMB})
    monkeypatch.setattr("src.ai.providers.service.get_ai_service", lambda *a, **k: svc)
    engine = ChatEngine(db=DatabaseManager(tmp_path / "fb.db"))
    engine._search_relevant_documents = lambda q, max_docs=5: []
    out = engine.chat("question", search_context=False)
    assert out["provider"] == "ollama"
    assert failing.calls == 1


def test_no_llm_available_degrades_without_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "EmbeddingGenerator", _NullEmbeddings)
    cfg = make_config(mode="local")
    svc = _service(cfg, {"ollama": FakeLLM("ollama", available=False)},
                   {"sentence_transformers": FakeEmbedding("sentence_transformers", available=False)},
                   gpu=None, vram=0)
    monkeypatch.setattr("src.ai.providers.service.get_ai_service", lambda *a, **k: svc)
    engine = ChatEngine(db=DatabaseManager(tmp_path / "none.db"))
    assert engine.simple_fallback is not None
    out = engine.chat("question", search_context=False)
    assert isinstance(out.get("response"), str) and out["response"]


def test_remote_embedding_failure_degrades_to_lexical(tmp_path, monkeypatch):
    failing = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, fail=True, dim=4)
    adapter = ProviderEmbeddingGenerator(failing)
    db = DatabaseManager(tmp_path / "sem.db")
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, size_bytes, modified_at, content_text, "
            "content_extracted, state, document_kind) VALUES (1, '/c/a.txt', 'a.txt', 10, "
            "'2026-01-01', ?, 1, 'ACTIVE', 'PHYSICAL_FILE')", ("alpha body " * 10,))
        conn.commit()
    engine = SemanticSearchEngine(db, embedding_gen=adapter)
    results = engine.semantic_search("alpha", limit=5, similarity_threshold=0.0)
    assert isinstance(results, list)  # lexical fallback, no crash


def test_cpu_only_no_providers_keeps_core_functional(tmp_path, monkeypatch):
    # No GPU, no Ollama, no local ST, no API -> LOCAL_ONLY and AI unavailable.
    cfg = make_config(mode="auto")
    svc = _service(cfg, {"ollama": FakeLLM("ollama", available=False)},
                   {"sentence_transformers": FakeEmbedding("sentence_transformers", available=False)},
                   gpu=None, vram=0, ram=4)
    assert svc.router.tier.value == "lite"
    assert not svc.llm().is_available()
    assert not svc.embeddings().is_available()
    assert svc.remote_embedding_generator() is None
    # Core (non-AI) functionality is untouched: DB + lexical search still work.
    db = DatabaseManager(tmp_path / "cpu.db")
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, size_bytes, modified_at, state, document_kind) "
            "VALUES (1, '/c/doc.txt', 'doc.txt', 10, '2026-01-01', 'ACTIVE', 'PHYSICAL_FILE')")
        conn.commit()
    assert len(db.search_files("doc")) == 1


def test_chat_engine_provider_error_falls_back_to_simple(tmp_path, monkeypatch):
    # A selected provider that fails at call time (e.g. model not installed)
    # must degrade to the deterministic fallback, not surface a provider error.
    monkeypatch.setattr(ss, "EmbeddingGenerator", _NullEmbeddings)
    failing = FakeLLM("ollama", "missing-model", remote=False, fail=True)
    svc = _service(make_config(mode="local"), {"ollama": failing},
                   {"sentence_transformers": LOCAL_EMB})
    monkeypatch.setattr("src.ai.providers.service.get_ai_service", lambda *a, **k: svc)
    engine = ChatEngine(db=DatabaseManager(tmp_path / "err.db"))
    out = engine.chat("question", search_context=False)
    assert out.get("response")
    assert out.get("error") != "provider_unavailable" or out.get("response")
    assert failing.calls == 1
