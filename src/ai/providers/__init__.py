"""AI provider abstraction (M012-A): contracts, local/remote providers, router."""
from .adapters import ProviderEmbeddingGenerator
from .base import (
    AIProviderError,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    ModelInfo,
    ProviderAuthError,
    ProviderCapabilities,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RemoteContentBlockedError,
)
from .config import AIConfig
from .policy import RemoteContentPolicy
from .router import (
    FallbackLLMProvider,
    HardwareTier,
    ProviderRouter,
    RoutingPolicy,
    hardware_tier,
)
from .service import AIService, get_ai_service, reset_ai_service
from .usage import UsageTracker

__all__ = [
    "AIProviderError",
    "EmbeddingProvider",
    "EmbeddingResult",
    "LLMProvider",
    "LLMResult",
    "ModelInfo",
    "ProviderAuthError",
    "ProviderCapabilities",
    "ProviderRateLimitError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RemoteContentBlockedError",
    "AIConfig",
    "RemoteContentPolicy",
    "FallbackLLMProvider",
    "HardwareTier",
    "ProviderRouter",
    "RoutingPolicy",
    "hardware_tier",
    "AIService",
    "get_ai_service",
    "reset_ai_service",
    "UsageTracker",
    "ProviderEmbeddingGenerator",
]
