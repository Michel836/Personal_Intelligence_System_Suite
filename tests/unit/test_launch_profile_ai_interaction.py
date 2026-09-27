"""Profile ↔ AI-mode interaction and privacy defaults (M012-B2).

The profile layer must only supply defaults; explicit AI configuration must win,
and the privacy default (`never`) must hold in every profile even when remote
credentials are present.
"""
from __future__ import annotations

import pytest

from src.ai.providers.config import AIConfig
from src.ai.providers.router import RoutingPolicy
from src.core.launch_profile import (
    LaunchProfile,
    apply_profile_defaults,
    profile_env_defaults,
)
from tests.ai_fakes import FakeEmbedding, FakeLLM, make_router, profile

API = {
    "PIS_API_KEY": "sk-not-a-real-key",
    "PIS_API_BASE_URL": "https://api.example/v1",
    "PIS_API_LLM_MODEL": "gpt",
    "PIS_API_EMBEDDING_MODEL": "emb",
}


def _router_for(config: AIConfig, **profile_kw):
    return make_router(
        config,
        llm_providers={
            "ollama": FakeLLM("ollama", "qwen", remote=False),
            "openai_compatible": FakeLLM("openai_compatible", "gpt", remote=True),
        },
        emb_providers={
            "sentence_transformers": FakeEmbedding("sentence_transformers", "bge-m3", dim=8),
            "openai_compatible": FakeEmbedding("openai_compatible_embeddings", "emb", remote=True, dim=8),
        },
        hardware_profile=profile(**profile_kw),
    )


def _apply(profile: LaunchProfile, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(API)
    env.update(extra or {})
    apply_profile_defaults(profile, env)
    return env


def test_lite_stays_local_only_even_with_api_credentials(monkeypatch) -> None:
    env = _apply(LaunchProfile.LITE)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config = AIConfig.from_env()
    assert config.mode == "local"
    assert not config.content_policy.allows_remote
    router = _router_for(config, gpu="RTX 3090", vram=24, ram=64)
    assert router.llm_policy is RoutingPolicy.LOCAL_ONLY
    assert router.embedding_policy is RoutingPolicy.LOCAL_ONLY
    assert router._describe_selection("llm")["remote"] is False
    assert router._describe_selection("embeddings")["remote"] is False


def test_smart_defaults_never_send_remote_content(monkeypatch) -> None:
    env = _apply(LaunchProfile.SMART)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config = AIConfig.from_env()
    assert config.mode == "auto"
    assert not config.content_policy.allows_remote
    router = _router_for(config, gpu="RTX 3090", vram=24, ram=64)
    # Privacy default dominates AUTO: no remote selection.
    assert router.llm_policy is RoutingPolicy.LOCAL_ONLY
    assert router.embedding_policy is RoutingPolicy.LOCAL_ONLY


def test_explicit_env_overrides_profile_defaults(monkeypatch) -> None:
    env = _apply(LaunchProfile.LITE, {"PIS_AI_MODE": "hybrid"})
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config = AIConfig.from_env()
    assert config.mode == "hybrid"  # explicit override wins over lite default
    assert not config.content_policy.allows_remote  # but policy stays never
    router = _router_for(config, gpu="RTX 3090", vram=24, ram=64)
    assert router.llm_policy is RoutingPolicy.LOCAL_ONLY


def test_explicit_policy_override_enables_remote_when_user_opts_in(monkeypatch) -> None:
    env = _apply(
        LaunchProfile.SMART,
        {"PIS_REMOTE_CONTENT_POLICY": "extracted_text", "PIS_AI_MODE": "hybrid"},
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config = AIConfig.from_env()
    router = _router_for(config, gpu="RTX 3090", vram=24, ram=64)
    # The user opted in explicitly; that is honoured (not blocked by the profile).
    assert router.llm_policy is RoutingPolicy.PREFER_REMOTE


def test_cpu_only_auto_does_not_crash() -> None:
    config = AIConfig(mode="auto")
    router = _router_for(config)  # hardware_profile: no GPU
    status = router.status(cheap=True)
    assert status["hardware_tier"] == "lite"
    assert status["llm"]["provider"] in {"ollama", "unavailable"}


@pytest.mark.parametrize("profile_name", list(LaunchProfile))
def test_every_profile_defaults_to_never_policy(profile_name: LaunchProfile) -> None:
    assert profile_env_defaults(profile_name)["PIS_REMOTE_CONTENT_POLICY"] == "never"
