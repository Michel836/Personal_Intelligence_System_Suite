"""AIService facade: the single entry point application code uses (M012-A).

Builds the router from configuration and exposes selection helpers. The local
proven path is preserved: when the router selects the local SentenceTransformer
provider, ``remote_embedding_generator`` returns ``None`` so the semantic engine
keeps using its own ``EmbeddingGenerator`` (unchanged store/provenance).
"""
from __future__ import annotations

import threading
from typing import Optional

from .adapters import ProviderEmbeddingGenerator
from .config import AIConfig
from .router import ProviderRouter
from .usage import UsageTracker


class AIService:
    def __init__(self, config: Optional[AIConfig] = None, *, router: Optional[ProviderRouter] = None,
                 usage: Optional[UsageTracker] = None, hardware_profile=None):
        self.config = config or AIConfig.from_env()
        self.usage = usage or UsageTracker()
        self.router = router or build_router(self.config, self.usage, hardware_profile)

    # -- selection ---------------------------------------------------------
    def llm(self, *, content_level: str = "text", model_override: Optional[str] = None):
        return self.router.llm(content_level=content_level, model_override=model_override)

    def embeddings(self, *, requires_text: bool = True):
        return self.router.embeddings(requires_text=requires_text)

    def remote_embedding_generator(self, *, requires_text: bool = True):
        """Adapter for a *remote* embedding selection, or ``None`` for local.

        Returning ``None`` keeps the local ``EmbeddingGenerator`` (and therefore
        the existing embedding store namespace) exactly as before. The local
        model is never constructed here.
        """
        if not self.router.embedding_selection_is_remote(requires_text=requires_text):
            return None
        provider = self.router.embeddings(requires_text=requires_text)
        info = provider.model_info()
        if not info.remote:
            return None
        return ProviderEmbeddingGenerator(provider)

    def status(self) -> dict:
        return self.router.status()


def build_router(config: AIConfig, usage: UsageTracker, hardware_profile=None) -> ProviderRouter:
    from .ollama import OllamaEmbeddingProvider, OllamaLLMProvider
    from .openai_compatible import (
        OpenAICompatibleEmbeddingProvider,
        OpenAICompatibleLLMProvider,
    )
    from .local import SentenceTransformerEmbeddingProvider

    llm_factories = {
        "ollama": lambda: OllamaLLMProvider(config.llm_model),
        "openai_compatible": lambda: OpenAICompatibleLLMProvider(
            model=config.api_llm_model or "",
            base_url=config.api_base_url or "",
            api_key=config.api_key,
            timeout=config.api_timeout,
            max_retries=config.api_max_retries,
        ),
    }
    embedding_factories = {
        "sentence_transformers": lambda: SentenceTransformerEmbeddingProvider(config.embedding_model),
        "ollama": lambda: OllamaEmbeddingProvider(config.embedding_model),
        "openai_compatible": lambda: OpenAICompatibleEmbeddingProvider(
            model=config.api_embedding_model or "",
            base_url=config.api_base_url or "",
            api_key=config.api_key,
            dim=config.api_embedding_dim,
            timeout=config.api_timeout,
            max_retries=config.api_max_retries,
        ),
    }
    return ProviderRouter(
        config,
        llm_factories=llm_factories,
        embedding_factories=embedding_factories,
        usage=usage,
        hardware_profile=hardware_profile,
    )


_service: Optional[AIService] = None
_service_lock = threading.Lock()


def get_ai_service(config: Optional[AIConfig] = None) -> AIService:
    """Process-wide AIService (lazily built from the environment)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = AIService(config)
    return _service


def reset_ai_service() -> None:
    """Clear the cached service (tests / after changing the environment)."""
    global _service
    with _service_lock:
        _service = None
