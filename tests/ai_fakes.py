"""Shared fakes/helpers for AI provider tests (M012-A). No network, no keys."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional, Sequence

from src.ai.providers.base import (
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    ModelInfo,
    ProviderResponseError,
    ProviderUnavailableError,
)
from src.ai.providers.config import AIConfig
from src.ai.providers.policy import RemoteContentPolicy
from src.ai.providers.router import ProviderRouter


# --- fake HTTP (OpenAI-compatible) ----------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None, lines=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self._lines = lines or []
        self.closed = False

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def close(self):
        self.closed = True


class FakeSession:
    """Records POST calls and returns queued responses (exhaust then 200)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None, stream=False):
        self.calls.append({"url": url, "headers": dict(headers or {}), "json": json,
                           "timeout": timeout, "stream": stream})
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                  "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


# --- fake providers -------------------------------------------------------

class FakeLLM(LLMProvider):
    def __init__(self, name="fake_llm", model="fake-model", remote=False,
                 available=True, fail=False, response="hello from fake"):
        self.name = name
        self.backend = name
        self.remote = remote
        self.model = model
        self._available = available
        self.fail = fail
        self.response = response
        self.calls = 0
        self.last_messages = None

    def is_available(self):
        return self._available

    def model_info(self):
        return ModelInfo(provider=self.name, model=self.model, remote=self.remote)

    def chat(self, messages, *, options=None):
        self.calls += 1
        self.last_messages = list(messages)
        if self.fail:
            raise ProviderResponseError("simulated failure")
        return LLMResult(text=self.response, provider=self.name, model=self.model)


class FakeEmbedding(EmbeddingProvider):
    def __init__(self, name="fake_emb", model="fake-emb-model", remote=False,
                 dim=4, available=True, fail=False):
        self.name = name
        self.backend = name
        self.remote = remote
        self.model = model
        self._dim = dim
        self._available = available
        self.fail = fail
        self.calls = 0

    def is_available(self):
        return self._available

    def dimension(self):
        return self._dim

    def model_info(self):
        return ModelInfo(provider=self.name, model=self.model, remote=self.remote, dimension=self._dim)

    def embed_batch(self, texts, *, batch_size=None):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailableError("simulated embedding outage")
        return EmbeddingResult(
            vectors=[[float((len(t) + i) % 7) for i in range(self._dim)] for t in texts],
            provider=self.name, model=self.model, dim=self._dim,
        )


# --- helpers --------------------------------------------------------------

def profile(*, gpu=None, vram=0.0, ram=32.0):
    return SimpleNamespace(gpu_name=gpu, vram_gb=vram, ram_gb=ram, logical_cpus=8,
                           physical_cores=4)


def make_config(**kw) -> AIConfig:
    base = dict(mode="auto", content_policy=RemoteContentPolicy.NEVER)
    base.update(kw)
    return AIConfig(**base)


def make_router(config: AIConfig, *, llm_providers: Optional[dict] = None,
                emb_providers: Optional[dict] = None, hardware_profile=None,
                ollama=True, st=True) -> ProviderRouter:
    llm_providers = llm_providers or {}
    emb_providers = emb_providers or {}
    return ProviderRouter(
        config,
        llm_factories={k: (lambda p=p: p) for k, p in llm_providers.items()},
        embedding_factories={k: (lambda p=p: p) for k, p in emb_providers.items()},
        hardware_profile=hardware_profile,
        ollama_available=lambda: ollama,
        sentence_transformers_available=lambda: st,
    )
