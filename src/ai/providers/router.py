"""Provider router: chooses LLM/embedding backends from mode, policy, hardware
and availability, and enforces the remote-content policy at the provider
boundary (M012-A).

Design notes
------------
* Local providers are never restricted by the privacy policy; remote providers
  are only reachable when the policy permits the content being sent.
* ``PIS_AI_MODE=local`` (and any ``never`` policy) yields a local-only chain, so
  no remote HTTP call is ever made.
* LLM chains support ordered fallback (PREFER_*). Embedding selection returns a
  single best provider; the semantic engine degrades to lexical search if it
  fails.
* Providers are constructed lazily so selecting a remote backend never loads a
  local model (and vice-versa).
"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, Optional, Sequence

from loguru import logger

from .base import (
    AIProviderError,
    EmbeddingProvider,
    LLMProvider,
    ProviderUnavailableError,
    RemoteContentBlockedError,
)
from .config import AIConfig
from .usage import UsageTracker


class RoutingPolicy(str, Enum):
    LOCAL_ONLY = "local_only"
    PREFER_LOCAL = "prefer_local"
    PREFER_REMOTE = "prefer_remote"
    REMOTE_ONLY = "remote_only"


class HardwareTier(str, Enum):
    LITE = "lite"
    BALANCED = "balanced"
    PERFORMANCE = "performance"


def hardware_tier(profile=None) -> HardwareTier:
    """Capability tier from measured resources (never a machine identity)."""
    if profile is None:
        from ...core.perf_config import HardwareProfile

        profile = HardwareProfile.detect()
    has_gpu = bool(getattr(profile, "gpu_name", None))
    vram = float(getattr(profile, "vram_gb", 0.0) or 0.0)
    ram = float(getattr(profile, "ram_gb", 0.0) or 0.0)
    if has_gpu and vram >= 16 and ram >= 32:
        return HardwareTier.PERFORMANCE
    if has_gpu and vram >= 6:
        return HardwareTier.BALANCED
    return HardwareTier.LITE


# --- unavailable / fallback providers -------------------------------------

class _UnavailableLLM(LLMProvider):
    name = "unavailable"
    remote = False

    def __init__(self, reason: str):
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def model_info(self):
        from .base import ModelInfo

        return ModelInfo(provider="unavailable", model="", remote=False)

    def chat(self, messages, *, options=None):
        raise ProviderUnavailableError(self.reason)

    def stream_chat(self, messages, *, options=None):
        raise ProviderUnavailableError(self.reason)


class _UnavailableEmbedding(EmbeddingProvider):
    name = "unavailable"
    remote = False

    def __init__(self, reason: str):
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def dimension(self) -> int:
        return 0

    def model_info(self):
        from .base import ModelInfo

        return ModelInfo(provider="unavailable", model="", remote=False)

    def embed_batch(self, texts, *, batch_size=None):
        raise ProviderUnavailableError(self.reason)


class FallbackLLMProvider(LLMProvider):
    """Try providers in order; only fall back on provider errors."""

    name = "fallback"

    def __init__(self, providers: Sequence[LLMProvider]):
        self._providers = list(providers)
        self.remote = bool(self._providers and all(p.remote for p in self._providers))

    def is_available(self) -> bool:
        return any(p.is_available() for p in self._providers)

    def model_info(self):
        return self._providers[0].model_info()

    def chain(self) -> list[str]:
        return [p.name for p in self._providers]

    def chat(self, messages, *, options=None):
        last: Optional[Exception] = None
        for provider in self._providers:
            try:
                return provider.chat(messages, options=options)
            except RemoteContentBlockedError:
                raise
            except AIProviderError as exc:
                logger.warning(f"LLM provider {provider.name} failed, trying next: {exc}")
                last = exc
        raise last or ProviderUnavailableError("no LLM provider available")

    def stream_chat(self, messages, *, options=None):
        last: Optional[Exception] = None
        for provider in self._providers:
            try:
                yield from provider.stream_chat(messages, options=options)
                return
            except RemoteContentBlockedError:
                raise
            except AIProviderError as exc:
                logger.warning(f"LLM provider {provider.name} stream failed: {exc}")
                last = exc
        raise last or ProviderUnavailableError("no LLM provider available")


class MeteredLLMProvider(LLMProvider):
    """Records request/token/latency usage for the provider it wraps."""

    def __init__(self, provider: LLMProvider, tracker: UsageTracker):
        self._provider = provider
        self._tracker = tracker
        self.name = provider.name
        self.remote = provider.remote

    def is_available(self) -> bool:
        return self._provider.is_available()

    def model_info(self):
        return self._provider.model_info()

    def chain(self):
        inner = getattr(self._provider, "chain", None)
        return inner() if callable(inner) else [self._provider.name]

    @property
    def model(self):
        return getattr(self._provider, "model", None)

    @model.setter
    def model(self, value):
        if hasattr(self._provider, "model"):
            self._provider.model = value

    def chat(self, messages, *, options=None):
        start = time.perf_counter()
        result = self._provider.chat(messages, options=options)
        self._tracker.record(result.provider, result.model, "llm_chat",
                             usage=result.usage, latency=time.perf_counter() - start)
        return result

    def stream_chat(self, messages, *, options=None):
        start = time.perf_counter()
        info = self._provider.model_info()
        for chunk in self._provider.stream_chat(messages, options=options):
            yield chunk
        self._tracker.record(info.provider, info.model, "llm_stream", latency=time.perf_counter() - start)


class MeteredEmbeddingProvider(EmbeddingProvider):
    """Records request/token/latency usage for the embedding provider it wraps."""

    def __init__(self, provider: EmbeddingProvider, tracker: UsageTracker):
        self._provider = provider
        self._tracker = tracker
        self.name = provider.name
        self.remote = provider.remote

    def is_available(self) -> bool:
        return self._provider.is_available()

    def dimension(self) -> int:
        return self._provider.dimension()

    def model_info(self):
        return self._provider.model_info()

    def embed_batch(self, texts, *, batch_size=None):
        start = time.perf_counter()
        result = self._provider.embed_batch(texts, batch_size=batch_size)
        self._tracker.record(result.provider, result.model, "embeddings",
                             usage=result.usage, latency=time.perf_counter() - start)
        return result


# --- router ---------------------------------------------------------------

class ProviderRouter:
    def __init__(
        self,
        config: AIConfig,
        *,
        llm_factories: dict[str, Callable[[], LLMProvider]],
        embedding_factories: dict[str, Callable[[], EmbeddingProvider]],
        usage: Optional[UsageTracker] = None,
        hardware_profile=None,
        ollama_available: Optional[Callable[[], bool]] = None,
        sentence_transformers_available: Optional[Callable[[], bool]] = None,
    ):
        self.config = config
        self._llm_factories = llm_factories
        self._embedding_factories = embedding_factories
        self.usage = usage or UsageTracker()
        self.profile = hardware_profile
        self.tier = hardware_tier(hardware_profile)
        self._lock = threading.Lock()
        self._llm_cache: dict[str, LLMProvider] = {}
        self._embedding_cache: dict[str, EmbeddingProvider] = {}
        self._ollama_probe = ollama_available or _default_ollama_probe
        self._st_probe = sentence_transformers_available or _default_st_probe

    # -- candidate order ---------------------------------------------------
    def _llm_order(self, policy: RoutingPolicy) -> list[str]:
        local, remote = ["ollama"], ["openai_compatible"]
        if self.config.llm_backend != "auto":
            return [self.config.llm_backend]
        if policy is RoutingPolicy.LOCAL_ONLY:
            return local
        if policy is RoutingPolicy.PREFER_LOCAL:
            return local + remote
        if policy is RoutingPolicy.PREFER_REMOTE:
            return remote + local
        return remote

    def _embedding_order(self, policy: RoutingPolicy) -> list[str]:
        local, remote = ["sentence_transformers", "ollama"], ["openai_compatible"]
        if self.config.embedding_backend != "auto":
            return [self.config.embedding_backend]
        if policy is RoutingPolicy.LOCAL_ONLY:
            return local
        if policy is RoutingPolicy.PREFER_LOCAL:
            return local + remote
        if policy is RoutingPolicy.PREFER_REMOTE:
            return remote + local
        return remote

    # -- policy / availability --------------------------------------------
    def _allowed(self, backend: str, *, requires_text: bool) -> bool:
        if backend != "openai_compatible":
            return True
        policy = self.config.content_policy
        if not policy.allows_remote:
            return False
        if requires_text and not policy.allows_extracted_text:
            return False
        return True

    def _cheap_available(self, kind: str, backend: str) -> bool:
        if backend == "openai_compatible":
            if kind == "llm":
                return self.config.remote_llm_configured()
            return self.config.remote_embeddings_configured()
        if backend == "ollama":
            return bool(self._ollama_probe())
        if backend == "sentence_transformers":
            return bool(self._st_probe())
        return False

    def _provider(self, kind: str, backend: str):
        cache = self._llm_cache if kind == "llm" else self._embedding_cache
        factories = self._llm_factories if kind == "llm" else self._embedding_factories
        with self._lock:
            if backend not in cache:
                cache[backend] = factories[backend]()
            return cache[backend]

    # -- public selection --------------------------------------------------
    def llm(self, *, content_level: str = "none", model_override: str | None = None) -> LLMProvider:
        requires_text = content_level == "text"
        policy = self.llm_policy
        chain: list[LLMProvider] = []
        for backend in self._llm_order(policy):
            if not self._allowed(backend, requires_text=requires_text):
                continue
            if not self._cheap_available("llm", backend):
                continue
            try:
                provider = self._provider("llm", backend)
                if provider.is_available():
                    chain.append(provider)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"LLM provider {backend} unavailable: {exc}")
        if not chain:
            return _UnavailableLLM(
                "no LLM provider available for the current mode/policy/backend"
            )
        if model_override:
            # Explicit model selection must win over the provider default.
            for provider in chain:
                if hasattr(provider, "model"):
                    provider.model = model_override
        if len(chain) == 1:
            return MeteredLLMProvider(chain[0], self.usage)
        return MeteredLLMProvider(FallbackLLMProvider(chain), self.usage)

    def embeddings(self, *, requires_text: bool = True) -> EmbeddingProvider:
        policy = self.embedding_policy
        for backend in self._embedding_order(policy):
            if not self._allowed(backend, requires_text=requires_text):
                continue
            if not self._cheap_available("embeddings", backend):
                continue
            try:
                provider = self._provider("embeddings", backend)
                if provider.is_available():
                    return MeteredEmbeddingProvider(provider, self.usage)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"embedding provider {backend} unavailable: {exc}")
        return _UnavailableEmbedding(
            "no embedding provider available for the current mode/policy/backend"
        )

    def embedding_selection_is_remote(self, *, requires_text: bool = True) -> bool:
        """Whether the preferred embedding backend is remote, without building it.

        Uses only cheap capability probes so callers can decide whether to keep
        the local ``EmbeddingGenerator`` without loading a local model.
        """
        for backend in self._embedding_order(self.embedding_policy):
            if not self._allowed(backend, requires_text=requires_text):
                continue
            if not self._cheap_available("embeddings", backend):
                continue
            return backend == "openai_compatible"
        return False

    # -- policies ----------------------------------------------------------
    @property
    def llm_policy(self) -> RoutingPolicy:
        return self._policies()[0]

    @property
    def embedding_policy(self) -> RoutingPolicy:
        return self._policies()[1]

    def _policies(self) -> tuple[RoutingPolicy, RoutingPolicy]:
        mode = self.config.mode
        policy = self.config.content_policy
        if mode == "local":
            return RoutingPolicy.LOCAL_ONLY, RoutingPolicy.LOCAL_ONLY
        if mode == "hybrid":
            llm = RoutingPolicy.PREFER_REMOTE if policy.allows_remote else RoutingPolicy.LOCAL_ONLY
            emb = RoutingPolicy.PREFER_LOCAL
            return llm, emb
        if mode == "api":
            llm = RoutingPolicy.REMOTE_ONLY if (self.config.remote_llm_configured() and policy.allows_remote) else RoutingPolicy.LOCAL_ONLY
            emb = RoutingPolicy.REMOTE_ONLY if (self.config.remote_embeddings_configured() and policy.allows_extracted_text) else RoutingPolicy.PREFER_LOCAL
            return llm, emb
        return self._auto_policies()

    def _auto_policies(self) -> tuple[RoutingPolicy, RoutingPolicy]:
        policy = self.config.content_policy
        if not policy.allows_remote:
            return RoutingPolicy.LOCAL_ONLY, RoutingPolicy.LOCAL_ONLY
        remote_llm = self.config.remote_llm_configured()
        remote_emb = self.config.remote_embeddings_configured() and policy.allows_extracted_text
        if self.tier is HardwareTier.LITE:
            llm = RoutingPolicy.PREFER_REMOTE if remote_llm else RoutingPolicy.LOCAL_ONLY
            emb = RoutingPolicy.PREFER_REMOTE if remote_emb else RoutingPolicy.PREFER_LOCAL
            return llm, emb
        if self.tier is HardwareTier.BALANCED:
            llm = RoutingPolicy.PREFER_REMOTE if remote_llm else RoutingPolicy.LOCAL_ONLY
            emb = RoutingPolicy.PREFER_LOCAL
            return llm, emb
        # PERFORMANCE: keep embeddings local, offload LLM when configured.
        llm = RoutingPolicy.PREFER_REMOTE if remote_llm else RoutingPolicy.PREFER_LOCAL
        return llm, RoutingPolicy.PREFER_LOCAL

    # -- diagnostics -------------------------------------------------------
    def _default_model_for(self, kind: str, backend: str) -> str | None:
        if kind == "llm":
            if backend == "openai_compatible":
                return self.config.api_llm_model
            return self.config.llm_model
        if backend == "openai_compatible":
            return self.config.api_embedding_model
        return self.config.embedding_model

    def _describe_selection(self, kind: str) -> dict:
        """Describe the selected backend using only cheap probes.

        Never constructs a provider, so a status render cannot load a local
        embedding model (M012-B2 lazy-startup requirement).
        """
        policy = self.llm_policy if kind == "llm" else self.embedding_policy
        order = self._llm_order(policy) if kind == "llm" else self._embedding_order(policy)
        requires_text = kind == "embeddings"
        for backend in order:
            if not self._allowed(backend, requires_text=requires_text):
                continue
            if not self._cheap_available(kind, backend):
                continue
            return {
                "provider": backend,
                "model": self._default_model_for(kind, backend),
                "remote": backend == "openai_compatible",
                "available": True,
                "policy": policy.value,
                "fallback_chain": None,
            }
        return {
            "provider": "unavailable",
            "model": "",
            "remote": None,
            "available": False,
            "policy": policy.value,
            "fallback_chain": None,
        }

    def status(self, *, cheap: bool = False) -> dict:
        def describe(provider, policy) -> dict:
            try:
                info = provider.model_info()
                return {
                    "provider": info.provider,
                    "model": info.model,
                    "remote": info.remote,
                    "available": provider.is_available(),
                    "policy": policy.value,
                    "fallback_chain": (provider.chain() if callable(getattr(provider, "chain", None)) else None),
                }
            except Exception:  # noqa: BLE001
                return {"provider": "unknown", "model": "", "remote": None,
                        "available": False, "policy": policy.value, "fallback_chain": None}

        if cheap:
            llm_entry = self._describe_selection("llm")
            emb_entry = self._describe_selection("embeddings")
        else:
            llm_entry = describe(self.llm(), self.llm_policy)
            emb_entry = describe(self.embeddings(), self.embedding_policy)
        profile = self.profile
        return {
            "config": self.config.public_dict(),
            "hardware_tier": self.tier.value,
            "gpu": {
                "name": getattr(profile, "gpu_name", None) if profile else None,
                "vram_gb": getattr(profile, "vram_gb", 0.0) if profile else 0.0,
                "ram_gb": getattr(profile, "ram_gb", 0.0) if profile else 0.0,
            },
            "llm": llm_entry,
            "embeddings": emb_entry,
            "usage": self.usage.snapshot(),
        }


def _default_ollama_probe() -> bool:
    try:
        from .ollama import OLLAMA_AVAILABLE

        return bool(OLLAMA_AVAILABLE)
    except Exception:  # noqa: BLE001
        return False


def _default_st_probe() -> bool:
    # Use find_spec rather than importing ``sentence_transformers``: importing it
    # pulls in torch (~1 GB RSS, several seconds) purely to answer "available?".
    try:
        import importlib.util

        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:  # noqa: BLE001
        return False
