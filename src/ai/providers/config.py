"""AI provider configuration resolved from the environment (M012-A).

Never logs or exposes API keys. ``public_dict`` is safe for UI/diagnostics.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .policy import RemoteContentPolicy

_MODES = {"local", "hybrid", "api", "auto"}
_LLM_BACKENDS = {"ollama", "openai_compatible", "auto"}
_EMBEDDING_BACKENDS = {"sentence_transformers", "ollama", "openai_compatible", "auto"}


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AIConfig:
    mode: str = "auto"
    content_policy: RemoteContentPolicy = RemoteContentPolicy.NEVER
    llm_backend: str = "auto"
    embedding_backend: str = "auto"
    llm_model: Optional[str] = None
    embedding_model: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_llm_model: Optional[str] = None
    api_embedding_model: Optional[str] = None
    api_embedding_dim: Optional[int] = None
    api_timeout: float = 60.0
    api_max_retries: int = 3
    _raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls) -> "AIConfig":
        mode = (_env("PIS_AI_MODE", "auto") or "auto").strip().lower()
        if mode not in _MODES:
            mode = "auto"
        llm_backend = (_env("PIS_LLM_BACKEND", "auto") or "auto").strip().lower()
        if llm_backend not in _LLM_BACKENDS:
            llm_backend = "auto"
        emb_backend = (_env("PIS_EMBEDDING_BACKEND", "auto") or "auto").strip().lower()
        if emb_backend not in _EMBEDDING_BACKENDS:
            emb_backend = "auto"
        dim = _env("PIS_API_EMBEDDING_DIM")
        return cls(
            mode=mode,
            content_policy=RemoteContentPolicy.from_env(),
            llm_backend=llm_backend,
            embedding_backend=emb_backend,
            llm_model=_env("PIS_LLM_MODEL"),
            embedding_model=_env("PIS_EMBEDDING_MODEL"),
            api_base_url=_env("PIS_API_BASE_URL"),
            api_key=_env("PIS_API_KEY"),
            api_llm_model=_env("PIS_API_LLM_MODEL"),
            api_embedding_model=_env("PIS_API_EMBEDDING_MODEL"),
            api_embedding_dim=int(dim) if dim else None,
            api_timeout=_env_float("PIS_API_TIMEOUT", 60.0),
            api_max_retries=max(0, _env_int("PIS_API_MAX_RETRIES", 3)),
        )

    # -- helpers -----------------------------------------------------------
    def api_configured(self) -> bool:
        return bool(self.api_base_url and self.api_key)

    def remote_llm_configured(self) -> bool:
        return self.api_configured() and bool(self.api_llm_model)

    def remote_embeddings_configured(self) -> bool:
        return self.api_configured() and bool(self.api_embedding_model)

    def public_dict(self) -> dict:
        """Diagnostics-safe view: the API key is reduced to a presence flag."""
        return {
            "mode": self.mode,
            "content_policy": self.content_policy.value,
            "llm_backend": self.llm_backend,
            "embedding_backend": self.embedding_backend,
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "api_base_url": self.api_base_url,
            "api_configured": self.api_configured(),
            "api_key_present": bool(self.api_key),
            "api_llm_model": self.api_llm_model,
            "api_embedding_model": self.api_embedding_model,
            "api_timeout": self.api_timeout,
            "api_max_retries": self.api_max_retries,
        }
