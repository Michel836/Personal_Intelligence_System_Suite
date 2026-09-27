"""Contracts, configuration and privacy policy tests (M012-A)."""
from __future__ import annotations

from src.ai.providers.base import (
    AIProviderError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RemoteContentBlockedError,
)
from src.ai.providers.config import AIConfig
from src.ai.providers.policy import RemoteContentPolicy


def test_error_hierarchy():
    for cls in (ProviderAuthError, ProviderRateLimitError, ProviderResponseError,
                ProviderTimeoutError, ProviderUnavailableError, RemoteContentBlockedError):
        assert issubclass(cls, AIProviderError)


def test_policy_from_env_and_flags(monkeypatch):
    monkeypatch.delenv("PIS_REMOTE_CONTENT_POLICY", raising=False)
    assert RemoteContentPolicy.from_env() is RemoteContentPolicy.NEVER
    assert not RemoteContentPolicy.NEVER.allows_remote
    assert not RemoteContentPolicy.METADATA_ONLY.allows_extracted_text
    assert RemoteContentPolicy.METADATA_ONLY.allows_remote
    assert RemoteContentPolicy.EXTRACTED_TEXT.allows_extracted_text
    assert not RemoteContentPolicy.EXTRACTED_TEXT.allows_full_context
    assert RemoteContentPolicy.FULL_CONTEXT.allows_full_context
    monkeypatch.setenv("PIS_REMOTE_CONTENT_POLICY", "bogus")
    assert RemoteContentPolicy.from_env() is RemoteContentPolicy.NEVER


def test_config_from_env_defaults_and_parse(monkeypatch):
    for k in ("PIS_AI_MODE", "PIS_LLM_BACKEND", "PIS_EMBEDDING_BACKEND", "PIS_REMOTE_CONTENT_POLICY",
              "PIS_API_BASE_URL", "PIS_API_KEY", "PIS_API_LLM_MODEL", "PIS_API_EMBEDDING_MODEL"):
        monkeypatch.delenv(k, raising=False)
    cfg = AIConfig.from_env()
    assert cfg.mode == "auto"
    assert cfg.content_policy is RemoteContentPolicy.NEVER
    assert not cfg.api_configured()

    monkeypatch.setenv("PIS_AI_MODE", "hybrid")
    monkeypatch.setenv("PIS_LLM_BACKEND", "openai_compatible")
    monkeypatch.setenv("PIS_EMBEDDING_BACKEND", "nonsense")
    monkeypatch.setenv("PIS_API_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("PIS_API_KEY", "sk-secret")
    monkeypatch.setenv("PIS_API_LLM_MODEL", "gpt-test")
    cfg = AIConfig.from_env()
    assert cfg.mode == "hybrid"
    assert cfg.llm_backend == "openai_compatible"
    assert cfg.embedding_backend == "auto"  # invalid -> auto
    assert cfg.api_configured() and cfg.remote_llm_configured()


def test_config_public_dict_never_exposes_key():
    cfg = AIConfig(api_base_url="https://api.example/v1", api_key="sk-secret-value",
                   api_llm_model="m")
    public = cfg.public_dict()
    assert "sk-secret-value" not in str(public)
    assert public["api_key_present"] is True
    assert public["api_configured"] is True
