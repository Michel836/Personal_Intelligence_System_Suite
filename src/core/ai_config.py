"""Model-role configuration for optional local AI providers (M009H.8).

Roles are resolved from ``PIS_MODEL_<ROLE>`` environment variables, falling back
to a default. No model is *required*: callers must degrade gracefully when the
provider/model is absent.
"""
from __future__ import annotations

import os

# Sensible local defaults; override with PIS_MODEL_INTERACTIVE_CHAT etc.
DEFAULT_MODELS: dict[str, str] = {
    "interactive_chat": "qwen3:8b",
    "high_quality": "qwen3:27b",
    "code": "qwen3-coder",
    "embedding": "nomic-embed-text",
}


def model_for(role: str) -> str:
    """Resolve a model name for a role, or ``""`` if unknown."""
    env_name = f"PIS_MODEL_{role.upper()}"
    return os.environ.get(env_name) or DEFAULT_MODELS.get(role, "")


def llm_think() -> bool:
    """Whether reasoning-mode models should emit hidden thinking tokens.

    Disabled by default: reasoning models (Qwen3.x) otherwise spend the whole
    generation budget in the thinking channel and return an empty answer.
    """
    return os.environ.get("PIS_LLM_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}
