"""Stable AI provider contracts (M012-A).

Application code depends on these interfaces, never on a specific vendor. Every
backend-specific failure is normalised into an :class:`AIProviderError` subclass
so callers can degrade gracefully.

Remote providers perform network I/O; local providers never leave the process.
The router (``router.py``) is the only place that decides which is used, and it
enforces the remote-content policy at this boundary.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Sequence


# --- errors ---------------------------------------------------------------

class AIProviderError(Exception):
    """Base class for normalised provider failures."""


class ProviderUnavailableError(AIProviderError):
    """Backend is missing, down, or not configured."""


class ProviderAuthError(AIProviderError):
    """Authentication/authorisation failure (e.g. HTTP 401/403)."""


class ProviderRateLimitError(AIProviderError):
    """Rate limited (e.g. HTTP 429); retryable after a delay."""


class ProviderTimeoutError(AIProviderError):
    """Request exceeded the configured timeout."""


class ProviderResponseError(AIProviderError):
    """Malformed, unexpected or server-side (5xx) response."""


class RemoteContentBlockedError(AIProviderError):
    """Remote content is disallowed by policy at the router boundary."""


class EmbeddingDimensionError(AIProviderError):
    """A provider returned a vector of an unexpected dimension."""


# --- results / metadata ---------------------------------------------------

@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    dim: int
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ProviderCapabilities:
    chat: bool = False
    stream: bool = False
    embeddings: bool = False
    remote: bool = False


@dataclass
class ModelInfo:
    provider: str
    model: str
    remote: bool = False
    dimension: Optional[int] = None
    context: Optional[int] = None


# --- contracts ------------------------------------------------------------

class LLMProvider(ABC):
    """Minimal chat-generation contract."""

    name: str = "base"
    remote: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap health check; must never raise."""

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat=True, stream=False, embeddings=False, remote=self.remote)

    @abstractmethod
    def model_info(self) -> ModelInfo:
        ...

    @abstractmethod
    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> LLMResult:
        """Run a chat completion. Raises an ``AIProviderError`` on failure."""

    def stream_chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        options: Optional[dict[str, Any]] = None,
    ) -> Iterator[str]:
        raise ProviderUnavailableError(f"{self.name}: streaming not supported")


class EmbeddingProvider(ABC):
    """Minimal embedding contract."""

    name: str = "base"
    remote: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        ...

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat=False, stream=False, embeddings=True, remote=self.remote)

    @abstractmethod
    def dimension(self) -> int:
        ...

    @abstractmethod
    def model_info(self) -> ModelInfo:
        ...

    @abstractmethod
    def embed_batch(
        self,
        texts: Sequence[str],
        *,
        batch_size: Optional[int] = None,
    ) -> EmbeddingResult:
        """Embed texts, preserving order. Raises ``AIProviderError`` on failure."""

    def embed(self, text: str) -> EmbeddingResult:
        return self.embed_batch([text])
