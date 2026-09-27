"""Usage/cost accounting tests (M012-A)."""
from __future__ import annotations

from src.ai.providers.base import LLMResult
from src.ai.providers.policy import RemoteContentPolicy
from src.ai.providers.usage import UsageTracker
from tests.ai_fakes import FakeEmbedding, FakeLLM, make_config, make_router, profile


def test_tracker_records_and_totals():
    tracker = UsageTracker()
    tracker.record("openai_compatible", "gpt", "llm_chat",
                   usage={"prompt_tokens": 10, "completion_tokens": 5}, latency=0.5)
    tracker.record("openai_compatible", "gpt", "llm_chat",
                   usage={"prompt_tokens": 2, "completion_tokens": 1}, latency=0.25)
    snap = tracker.snapshot()
    assert snap["totals"]["requests"] == 2
    assert snap["totals"]["prompt_tokens"] == 12
    assert snap["totals"]["completion_tokens"] == 6
    assert snap["buckets"]["openai_compatible:gpt:llm_chat"]["latency_s"] == 0.75
    assert snap["buckets"]["openai_compatible:gpt:llm_chat"]["estimated_cost_usd"] is None


def test_optional_price_table_estimates_cost():
    tracker = UsageTracker(price_table={("openai_compatible", "gpt"): (0.01, 0.03)})
    tracker.record("openai_compatible", "gpt", "llm_chat",
                   usage={"prompt_tokens": 1000, "completion_tokens": 1000})
    bucket = tracker.snapshot()["buckets"]["openai_compatible:gpt:llm_chat"]
    assert bucket["estimated_cost_usd"] == 0.04


def test_router_meters_llm_and_embeddings():
    tracker = UsageTracker()
    cfg = make_config(mode="hybrid", content_policy=RemoteContentPolicy.EXTRACTED_TEXT,
                      api_base_url="https://api.example/v1", api_key="sk",
                      api_llm_model="gpt", api_embedding_model="emb")
    router = make_router(cfg,
                         llm_providers={"openai_compatible": _UsageLLM()},
                         emb_providers={"openai_compatible": FakeEmbedding("openai_compatible_embeddings", "emb", remote=True)},
                         hardware_profile=profile(gpu=None, vram=0))
    router.usage = tracker
    router.llm(content_level="text").chat([{"role": "user", "content": "hi"}])
    router.embeddings().embed_batch(["a", "b"])
    snap = tracker.snapshot()
    assert snap["totals"]["requests"] == 2
    assert any(k.endswith(":llm_chat") for k in snap["buckets"])
    assert any(k.endswith(":embeddings") for k in snap["buckets"])


class _UsageLLM(FakeLLM):
    def __init__(self):
        super().__init__("openai_compatible", "gpt", remote=True)

    def chat(self, messages, *, options=None):
        self.calls += 1
        return LLMResult(text="hi", provider=self.name, model=self.model,
                         usage={"prompt_tokens": 3, "completion_tokens": 2})
