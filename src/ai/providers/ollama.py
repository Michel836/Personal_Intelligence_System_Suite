"""Ollama provider wrappers (local, never remote).

Thin adapters over the existing, proven local implementations. Ollama runs on
the same machine (or an explicitly configured host), so ``remote`` is False and
content never leaves the operator's infrastructure by default.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional, Sequence

from loguru import logger

from .base import (
    AIProviderError,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    ModelInfo,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency guard
    OLLAMA_AVAILABLE = False

from ...core.ai_config import llm_think


def _normalize_ollama_error(exc: Exception) -> AIProviderError:
    msg = str(exc)
    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return ProviderTimeoutError(msg)
    if "not found" in low or "connection" in low or "refused" in low or "unavailable" in low:
        return ProviderUnavailableError(msg)
    return ProviderResponseError(msg)


# Ollama health is probed over HTTP; cache it briefly so provider selection does
# not make a network round-trip on every chat/status call.
_AVAIL_TTL = max(0.0, float(os.environ.get("PIS_OLLAMA_AVAIL_TTL", "5")))
_avail_cache: dict[str, tuple[float, bool]] = {}
_avail_lock = threading.Lock()


def _cached_availability(base_url: str, probe) -> bool:
    now = time.monotonic()
    with _avail_lock:
        hit = _avail_cache.get(base_url)
        if hit is not None and (now - hit[0]) < _AVAIL_TTL:
            return hit[1]
    try:
        value = bool(probe())
    except Exception:  # noqa: BLE001
        value = False
    with _avail_lock:
        _avail_cache[base_url] = (time.monotonic(), value)
    return value


def _supports_think() -> bool:
    if not OLLAMA_AVAILABLE:
        return False
    try:
        import inspect

        return "think" in inspect.signature(ollama.chat).parameters
    except (TypeError, ValueError):
        return False


class OllamaLLMProvider(LLMProvider):
    """Local Ollama chat provider."""

    name = "ollama"
    backend = "ollama"
    remote = False

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None):
        from ...core.ai_config import model_for

        self.model = model or model_for("interactive_chat")
        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"

    def _client(self):
        client_cls = getattr(ollama, "Client", None)
        return client_cls(host=self.base_url) if client_cls else None

    def is_available(self) -> bool:
        if not OLLAMA_AVAILABLE:
            return False

        def _probe() -> bool:
            client = self._client()
            (client.list() if client else ollama.list())
            return True

        return _cached_availability(self.base_url, _probe)

    def model_info(self) -> ModelInfo:
        return ModelInfo(provider=self.name, model=self.model, remote=False)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> LLMResult:
        if not OLLAMA_AVAILABLE:
            raise ProviderUnavailableError("ollama python client is not installed")
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "options": dict(options or {}),
        }
        if _supports_think():
            kwargs["think"] = llm_think()
        try:
            client = self._client()
            response = client.chat(**kwargs) if client else ollama.chat(**kwargs)
        except AIProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"ollama chat failed: {exc}")
            raise _normalize_ollama_error(exc) from exc
        message = response.get("message") if isinstance(response, dict) else None
        text = (message or {}).get("content", "") if isinstance(message, dict) else ""
        eval_count = response.get("eval_count") if isinstance(response, dict) else None
        usage = {"completion_tokens": int(eval_count)} if eval_count else {}
        return LLMResult(text=text or "", provider=self.name, model=self.model,
                         usage=usage, raw=response if isinstance(response, dict) else None)

    def stream_chat(self, messages, *, options=None):
        if not OLLAMA_AVAILABLE:
            raise ProviderUnavailableError("ollama python client is not installed")
        kwargs: dict[str, Any] = {
            "model": self.model, "messages": list(messages),
            "options": dict(options or {}), "stream": True,
        }
        if _supports_think():
            kwargs["think"] = llm_think()
        try:
            client = self._client()
            stream = client.chat(**kwargs) if client else ollama.chat(**kwargs)
            for chunk in stream:
                msg = chunk.get("message") if isinstance(chunk, dict) else None
                if isinstance(msg, dict) and msg.get("content"):
                    yield msg["content"]
        except AIProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _normalize_ollama_error(exc) from exc


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Local Ollama embeddings, wrapping the existing generator."""

    name = "ollama_embeddings"
    backend = "ollama"
    remote = False

    def __init__(self, model: Optional[str] = None):
        from ...intelligence.ollama_embeddings import OllamaEmbeddingGenerator

        self.model = model or os.environ.get("PIS_EMBEDDING_MODEL") or "nomic-embed-text"
        self._gen = OllamaEmbeddingGenerator(self.model)

    def is_available(self) -> bool:
        def _probe() -> bool:
            return bool(self._gen.is_available())

        return _cached_availability(f"emb:{self.model}", _probe)

    def dimension(self) -> int:
        return int(self._gen.embedding_dim or 0)

    def model_info(self) -> ModelInfo:
        return ModelInfo(provider=self.name, model=self.model, remote=False,
                         dimension=self.dimension() or None)

    def embed_batch(self, texts: Sequence[str], *, batch_size: Optional[int] = None) -> EmbeddingResult:
        vectors = self._gen.generate_batch_embeddings(list(texts))
        out = [v.tolist() if v is not None else [] for v in vectors]
        return EmbeddingResult(vectors=out, provider=self.name, model=self.model,
                               dim=self.dimension())
