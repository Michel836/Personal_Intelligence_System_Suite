"""Ollama client compatibility + chat option bounds (M010 scale trial)."""
from __future__ import annotations

import types

import src.intelligence.chat_engine as ce


def test_think_kwarg_detected_only_when_supported(monkeypatch) -> None:
    monkeypatch.setattr(ce, "OLLAMA_AVAILABLE", True)

    def old_chat(model="", messages=None, stream=False, options=None):  # no ``think``
        return {}

    def new_chat(model="", messages=None, stream=False, options=None, think=False):
        return {}

    monkeypatch.setattr(ce, "ollama", types.SimpleNamespace(chat=old_chat))
    assert ce._ollama_supports_think() is False
    monkeypatch.setattr(ce, "ollama", types.SimpleNamespace(chat=new_chat))
    assert ce._ollama_supports_think() is True


def test_llm_generation_bounds_respect_env(monkeypatch) -> None:
    monkeypatch.delenv("PIS_LLM_NUM_CTX", raising=False)
    monkeypatch.delenv("PIS_LLM_MAX_TOKENS", raising=False)
    assert ce._llm_num_ctx() == 4096
    assert ce._llm_num_predict() == 384

    monkeypatch.setenv("PIS_LLM_NUM_CTX", "8192")
    monkeypatch.setenv("PIS_LLM_MAX_TOKENS", "256")
    assert ce._llm_num_ctx() == 8192
    assert ce._llm_num_predict() == 256

    monkeypatch.setenv("PIS_LLM_NUM_CTX", "not-a-number")
    monkeypatch.setenv("PIS_LLM_MAX_TOKENS", "not-a-number")
    assert ce._llm_num_ctx() == 4096
    assert ce._llm_num_predict() == 384
