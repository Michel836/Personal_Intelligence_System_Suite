"""AI status surface tests (M012-A): safe diagnostics, no secrets."""
from __future__ import annotations

from src.ai.providers.policy import RemoteContentPolicy
from src.ai.providers.service import AIService
from src.ui.ai_status import ai_status_lines
from tests.ai_fakes import FakeEmbedding, FakeLLM, make_config, make_router, profile

SECRET = "sk-do-not-display-this-key"


def _service():
    cfg = make_config(mode="hybrid", content_policy=RemoteContentPolicy.EXTRACTED_TEXT,
                      api_base_url="https://api.example/v1", api_key=SECRET,
                      api_llm_model="gpt", api_embedding_model="emb")
    router = make_router(cfg,
                         llm_providers={"ollama": FakeLLM("ollama", "qwen", remote=False),
                                        "openai_compatible": FakeLLM("openai_compatible", "gpt", remote=True)},
                         emb_providers={"sentence_transformers": FakeEmbedding("sentence_transformers", "bge-m3", dim=8)},
                         hardware_profile=profile(gpu="RTX 3090", vram=24, ram=64))
    return AIService(cfg, router=router)


def test_status_lines_are_safe_and_complete():
    status = ai_status_lines(_service())
    assert status["config"]["mode"] == "hybrid"
    assert status["config"]["content_policy"] == "extracted_text"
    assert status["hardware_tier"] == "performance"
    assert status["llm"]["provider"] in {"openai_compatible", "fallback"}
    assert status["embeddings"]["provider"] == "sentence_transformers"
    assert status["config"]["api_key_present"] is True
    assert SECRET not in str(status)


def test_status_render_does_not_raise():
    import pytest

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    service = _service()
    at = AppTest.from_function(lambda: __import__("src.ui.ai_status", fromlist=["render_ai_status"]).render_ai_status(service)).run()
    assert not at.exception
