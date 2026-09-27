"""Provider router tests: modes, policies, hardware tiers, fallback (M012-A)."""
from __future__ import annotations

from src.ai.providers.policy import RemoteContentPolicy
from src.ai.providers.router import (
    FallbackLLMProvider,
    HardwareTier,
    RoutingPolicy,
    hardware_tier,
)
from tests.ai_fakes import FakeEmbedding, FakeLLM, make_config, make_router, profile

REMOTE = FakeLLM("openai_compatible", "gpt-test", remote=True)
LOCAL = FakeLLM("ollama", "qwen-local", remote=False)
REMOTE_EMB = FakeEmbedding("openai_compatible_embeddings", "emb-remote", remote=True, dim=8)
LOCAL_EMB = FakeEmbedding("sentence_transformers", "bge-m3", remote=False, dim=8)


def _api_config(**kw):
    base = dict(mode="hybrid", api_base_url="https://api.example/v1", api_key="sk-x",
                api_llm_model="gpt-test", api_embedding_model="emb-remote",
                content_policy=RemoteContentPolicy.EXTRACTED_TEXT)
    base.update(kw)
    return make_config(**base)


def test_hardware_tiers():
    assert hardware_tier(profile(gpu=None, vram=0, ram=8)) is HardwareTier.LITE
    assert hardware_tier(profile(gpu="RTX 3060", vram=8, ram=16)) is HardwareTier.BALANCED
    assert hardware_tier(profile(gpu="RTX 3090", vram=24, ram=64)) is HardwareTier.PERFORMANCE


def test_local_mode_never_selects_remote():
    router = make_router(make_config(mode="local"), llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB},
                         hardware_profile=profile(gpu="RTX 3090", vram=24))
    assert router.llm_policy is RoutingPolicy.LOCAL_ONLY
    assert router.llm().name == "ollama"
    assert not router.llm().remote
    assert router.embeddings().name == "sentence_transformers"
    assert router.embedding_selection_is_remote() is False


def test_never_policy_blocks_remote_even_when_configured():
    router = make_router(_api_config(content_policy=RemoteContentPolicy.NEVER),
                         llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB},
                         hardware_profile=profile(gpu=None, vram=0))
    assert router.llm_policy is RoutingPolicy.LOCAL_ONLY
    assert router.llm().name == "ollama"
    assert router.embedding_selection_is_remote() is False


def test_hybrid_prefers_remote_llm_local_embeddings():
    router = make_router(_api_config(), llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB},
                         hardware_profile=profile(gpu="RTX 3090", vram=24))
    assert router.llm_policy is RoutingPolicy.PREFER_REMOTE
    assert router.embedding_policy is RoutingPolicy.PREFER_LOCAL
    llm = router.llm()
    assert llm.chain() == ["openai_compatible", "ollama"]
    assert router.embeddings().name == "sentence_transformers"


def test_prefer_remote_falls_back_to_local_on_failure():
    failing_remote = FakeLLM("openai_compatible", "gpt-test", remote=True, fail=True)
    router = make_router(_api_config(), llm_providers={"ollama": LOCAL, "openai_compatible": failing_remote},
                         emb_providers={"sentence_transformers": LOCAL_EMB},
                         hardware_profile=profile(gpu=None, vram=0))
    llm = router.llm()
    result = llm.chat([{"role": "user", "content": "hi"}])
    assert result.provider == "ollama"  # remote failed -> local fallback
    assert failing_remote.calls == 1


def test_metadata_only_excludes_text_remote_selects_metadata_chain():
    router = make_router(_api_config(content_policy=RemoteContentPolicy.METADATA_ONLY),
                         llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB},
                         hardware_profile=profile(gpu=None, vram=0))
    # text-level selection cannot use the remote provider -> local
    assert router.llm(content_level="text").name == "ollama"
    # metadata-level selection may use the remote provider (no body text)
    md = router.llm(content_level="metadata")
    first = md.chain()[0] if md.chain() else md.name
    assert first == "openai_compatible"
    # remote embeddings would send document text -> not selected under metadata_only
    assert router.embedding_selection_is_remote() is False


def test_extracted_text_allows_remote_embeddings_selection():
    router = make_router(_api_config(mode="api", content_policy=RemoteContentPolicy.EXTRACTED_TEXT),
                         llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB},
                         hardware_profile=profile(gpu=None, vram=0))
    assert router.llm_policy is RoutingPolicy.REMOTE_ONLY
    assert router.embedding_selection_is_remote() is True
    assert router.embeddings().name == "openai_compatible_embeddings"


def test_explicit_backend_overrides_mode():
    router = make_router(_api_config(mode="api", llm_backend="ollama"),
                         llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB},
                         hardware_profile=profile(gpu=None, vram=0))
    assert router.llm().name == "ollama"


def test_unavailable_when_nothing_available():
    router = make_router(make_config(mode="local"),
                         llm_providers={"ollama": FakeLLM("ollama", available=False)},
                         emb_providers={"sentence_transformers": FakeEmbedding("sentence_transformers", available=False)},
                         hardware_profile=profile(gpu=None, vram=0))
    assert router.llm().is_available() is False
    assert router.embeddings().is_available() is False


def test_auto_lite_tier_prefers_remote_when_configured():
    router = make_router(_api_config(mode="auto"), llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB},
                         hardware_profile=profile(gpu=None, vram=0, ram=8))
    assert router.tier is HardwareTier.LITE
    assert router.llm_policy is RoutingPolicy.PREFER_REMOTE
    assert router.embedding_selection_is_remote() is True


def test_auto_performance_keeps_embeddings_local():
    router = make_router(_api_config(mode="auto"), llm_providers={"ollama": LOCAL, "openai_compatible": REMOTE},
                         emb_providers={"sentence_transformers": LOCAL_EMB, "openai_compatible": REMOTE_EMB},
                         hardware_profile=profile(gpu="RTX 3090", vram=24, ram=64))
    assert router.tier is HardwareTier.PERFORMANCE
    assert router.embedding_selection_is_remote() is False


def test_fallback_chain_tries_each_provider_once():
    import pytest

    from src.ai.providers.base import AIProviderError

    failing_remote = FakeLLM("openai_compatible", "gpt", remote=True, fail=True)
    failing_local = FakeLLM("ollama", "qwen", remote=False, fail=True)
    router = make_router(_api_config(),
                         llm_providers={"ollama": failing_local, "openai_compatible": failing_remote},
                         emb_providers={"sentence_transformers": LOCAL_EMB},
                         hardware_profile=profile(gpu=None, vram=0))
    llm = router.llm()
    with pytest.raises(AIProviderError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert failing_remote.calls == 1 and failing_local.calls == 1  # no infinite fallback loop
