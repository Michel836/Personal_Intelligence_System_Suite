"""Model-role configuration tests (M009I.7)."""
from __future__ import annotations

from src.core.ai_config import DEFAULT_MODELS, llm_think, model_for


def test_role_defaults_and_overrides(monkeypatch) -> None:
    monkeypatch.delenv("PIS_MODEL_INTERACTIVE_CHAT", raising=False)
    assert model_for("interactive_chat") == DEFAULT_MODELS["interactive_chat"]
    monkeypatch.setenv("PIS_MODEL_INTERACTIVE_CHAT", "qwen3:14b")
    assert model_for("interactive_chat") == "qwen3:14b"


def test_unknown_role_is_empty() -> None:
    assert model_for("does-not-exist") == ""


def test_think_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PIS_LLM_THINK", raising=False)
    assert llm_think() is False
    monkeypatch.setenv("PIS_LLM_THINK", "1")
    assert llm_think() is True
