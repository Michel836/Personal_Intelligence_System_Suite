"""Launch profiles for the canonical application (M012-B2).

One canonical Streamlit app (``src/ui/app.py``) is launched through three
coherent *profiles* -- ``LITE``, ``SMART`` and ``FULL``.  A profile never forks
the UI: it only supplies **defaults** for AI mode, heavyweight processing and
capability exposure.  Explicit environment variables always win over profile
defaults, which is the core precedence rule of this module.

Design constraints
------------------
* No streamlit / torch / provider imports here: the module is deliberately tiny
  and import-safe so the launcher and the app can both use it at startup.
* No machine identity and no hard-coded paths/ports.  Defaults are capability
  based, not host based.
* ``PIS_REMOTE_CONTENT_POLICY=never`` is a default in every profile, so a
  profile can never widen the privacy policy on its own.

Env contract
------------
``PIS_LAUNCH_PROFILE``
    ``lite`` | ``smart`` | ``full``.  Unknown values fall back to
    :data:`DEFAULT_PROFILE` (the app stays usable); the CLI rejects them.
``PIS_AI_MODE``, ``PIS_HEAVY_PRELOAD``, ``PIS_OCR_ENABLED``,
``PIS_ARCHIVE_PROCESSING``, ``PIS_BACKGROUND_PROCESSING``,
``PIS_REMOTE_CONTENT_POLICY``
    Defaults set by the profile only when the operator did not set them.
``PIS_FEATURE_<CAPABILITY>``
    Per-capability override (``1``/``true``/``yes``/``on`` to force-enable,
    ``0``/``false``/``no``/``off`` to force-disable), applied on top of the
    profile capability set.
"""
from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "Capability",
    "LaunchProfile",
    "ProfileContract",
    "DEFAULT_PROFILE",
    "PREFERRED_PORTS",
    "PROFILES",
    "apply_profile_defaults",
    "capabilities_for",
    "current_profile",
    "has_capability",
    "parse_profile",
    "profile_env_defaults",
    "resolve_profile",
]


class LaunchProfile(str, Enum):
    """Supported launch profiles (all launch the same canonical app)."""

    LITE = "lite"
    SMART = "smart"
    FULL = "full"


#: Profile used when ``PIS_LAUNCH_PROFILE`` is unset.  ``FULL`` preserves the
#: historical behaviour of ``streamlit run src/ui/app.py`` (every page visible),
#: so a direct start never silently hides functionality.
DEFAULT_PROFILE = LaunchProfile.FULL


class Capability(str, Enum):
    """UI/module capabilities a profile may expose or defer."""

    # Core capabilities: available in every profile, never hidden by default.
    SCAN = "scan"
    SEARCH = "search"
    ADVANCED_SEARCH = "advanced_search"
    TAGS = "tags"
    DASHBOARD = "dashboard"
    STATISTICS = "statistics"
    VIEWER = "viewer"
    SETTINGS = "settings"
    ARCHIVE_VIEWER = "archive_viewer"
    DUPLICATES = "duplicates"
    INTELLIGENCE = "intelligence"
    GRAPH = "graph"

    # Advanced capabilities: exposed by SMART/FULL, hidden by default in LITE.
    SEMANTIC_SEARCH = "semantic_search"
    AI_CHAT = "ai_chat"
    ADVANCED_AI = "advanced_ai"
    VISUALIZATIONS = "visualizations"
    CLOUD_SYNC = "cloud_sync"
    AUTO_EXTRACT = "auto_extract"


CORE_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.SCAN,
        Capability.SEARCH,
        Capability.ADVANCED_SEARCH,
        Capability.TAGS,
        Capability.DASHBOARD,
        Capability.STATISTICS,
        Capability.VIEWER,
        Capability.SETTINGS,
        Capability.ARCHIVE_VIEWER,
        Capability.DUPLICATES,
        Capability.INTELLIGENCE,
        Capability.GRAPH,
    }
)

ADVANCED_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.SEMANTIC_SEARCH,
        Capability.AI_CHAT,
        Capability.ADVANCED_AI,
        Capability.VISUALIZATIONS,
        Capability.CLOUD_SYNC,
        Capability.AUTO_EXTRACT,
    }
)

#: Convenience ports close to the historical launchers.  They are only defaults:
#: the launcher auto-selects a free port when they are occupied and honours an
#: explicit ``--port`` / ``PIS_PORT`` override.
PREFERRED_PORTS: dict[LaunchProfile, int] = {
    LaunchProfile.LITE: 8510,
    LaunchProfile.SMART: 8504,
    LaunchProfile.FULL: 8501,
}

#: Base environment defaults per profile.  ``PIS_REMOTE_CONTENT_POLICY`` stays
#: ``never`` in *every* profile: a profile must never relax privacy by itself.
_PROFILE_ENV_DEFAULTS: dict[LaunchProfile, dict[str, str]] = {
    LaunchProfile.LITE: {
        "PIS_AI_MODE": "local",
        "PIS_REMOTE_CONTENT_POLICY": "never",
        "PIS_HEAVY_PRELOAD": "0",
        "PIS_OCR_ENABLED": "0",
        "PIS_ARCHIVE_PROCESSING": "0",
        "PIS_BACKGROUND_PROCESSING": "0",
    },
    LaunchProfile.SMART: {
        "PIS_AI_MODE": "auto",
        "PIS_REMOTE_CONTENT_POLICY": "never",
        "PIS_HEAVY_PRELOAD": "0",
        "PIS_OCR_ENABLED": "0",
        "PIS_ARCHIVE_PROCESSING": "1",
        "PIS_BACKGROUND_PROCESSING": "1",
    },
    LaunchProfile.FULL: {
        "PIS_AI_MODE": "auto",
        "PIS_REMOTE_CONTENT_POLICY": "never",
        "PIS_HEAVY_PRELOAD": "0",
        "PIS_OCR_ENABLED": "0",
        "PIS_ARCHIVE_PROCESSING": "1",
        "PIS_BACKGROUND_PROCESSING": "1",
    },
}

_PROFILE_CAPABILITIES: dict[LaunchProfile, frozenset[Capability]] = {
    LaunchProfile.LITE: CORE_CAPABILITIES,
    LaunchProfile.SMART: CORE_CAPABILITIES | ADVANCED_CAPABILITIES,
    LaunchProfile.FULL: CORE_CAPABILITIES | ADVANCED_CAPABILITIES,
}

_TRUTHY = {"1", "true", "yes", "on", "enabled"}
_FALSY = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class ProfileContract:
    """Resolved public shape of a profile (diagnostics-safe)."""

    profile: LaunchProfile
    description: str
    capabilities: frozenset[Capability]
    env_defaults: Mapping[str, str]
    preferred_port: int
    ai_mode_default: str

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "description": self.description,
            "capabilities": sorted(c.value for c in self.capabilities),
            "env_defaults": dict(self.env_defaults),
            "preferred_port": self.preferred_port,
            "ai_mode_default": self.ai_mode_default,
        }


_DESCRIPTIONS: dict[LaunchProfile, str] = {
    LaunchProfile.LITE: (
        "Fastest startup and lowest resource use: canonical scan/search/viewer/"
        "archive with no heavyweight AI preload and local-only AI."
    ),
    LaunchProfile.SMART: (
        "Hardware-aware defaults and adaptive AI selection: all capabilities "
        "available lazily, AUTO provider selection, local-only privacy default."
    ),
    LaunchProfile.FULL: (
        "Every implemented mono-user capability exposed with lazy loading: "
        "semantic search, RAG chat, extraction, OCR, visualizations and cloud "
        "sync, still constrained by the privacy policy."
    ),
}


def parse_profile(value: object, *, strict: bool = False) -> LaunchProfile:
    """Normalise a profile value.

    ``strict=False`` (application default) falls back to :data:`DEFAULT_PROFILE`
    for unknown/empty values so a typo never bricks startup.  ``strict=True``
    (CLI) raises ``ValueError`` so a typo is reported instead of silently
    launching the wrong profile.
    """
    if isinstance(value, LaunchProfile):
        return value
    if value is None or str(value).strip() == "":
        return DEFAULT_PROFILE
    raw = str(value).strip().lower()
    try:
        return LaunchProfile(raw)
    except ValueError:
        if strict:
            allowed = ", ".join(p.value for p in LaunchProfile)
            raise ValueError(
                f"unknown launch profile {value!r}; expected one of: {allowed}"
            ) from None
        return DEFAULT_PROFILE


def current_profile(env: Mapping[str, str] | None = None) -> LaunchProfile:
    """Return the profile selected by the environment (non-strict)."""
    env = os.environ if env is None else env
    return parse_profile(env.get("PIS_LAUNCH_PROFILE"))


def profile_env_defaults(profile: LaunchProfile) -> dict[str, str]:
    """Defaults contributed by *profile* (never includes explicit overrides)."""
    return dict(_PROFILE_ENV_DEFAULTS[profile])


def _env_flag(value: str, *, default: bool) -> bool:
    raw = value.strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return default


def capabilities_for(
    profile: LaunchProfile, env: Mapping[str, str] | None = None
) -> frozenset[Capability]:
    """Resolve the exposed capability set for *profile*.

    Profile membership is the base; ``PIS_FEATURE_<NAME>`` entries add or remove
    individual capabilities.  Core capabilities cannot be disabled: search, scan,
    viewer and settings must remain reachable in every profile.
    """
    env = os.environ if env is None else env
    caps: set[Capability] = set(_PROFILE_CAPABILITIES[profile])
    for cap in Capability:
        key = f"PIS_FEATURE_{cap.value.upper()}"
        if key not in env or env[key].strip() == "":
            continue
        if cap in CORE_CAPABILITIES:
            # Core is always exposed; an explicit value can only keep it on.
            continue
        enabled = _env_flag(env[key], default=cap in caps)
        if enabled:
            caps.add(cap)
        else:
            caps.discard(cap)
    return frozenset(caps)


def has_capability(
    capability: Capability,
    profile: LaunchProfile | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Whether *capability* is exposed for the current/supplied profile."""
    env = os.environ if env is None else env
    profile = profile or current_profile(env)
    return capability in capabilities_for(profile, env)


def apply_profile_defaults(
    profile: LaunchProfile,
    env: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Apply *profile* defaults to *env*, only where no explicit value exists.

    Returns the mapping of variables actually written (defaults applied).  An
    empty or missing value counts as "not set"; any non-empty value set by the
    operator is preserved untouched, which is how explicit overrides win.
    """
    env = os.environ if env is None else env
    applied: dict[str, str] = {}

    def _setdefault(key: str, value: str) -> None:
        if not env.get(key, "").strip():
            env[key] = value
            applied[key] = value

    _setdefault("PIS_LAUNCH_PROFILE", profile.value)
    for key, value in _PROFILE_ENV_DEFAULTS[profile].items():
        _setdefault(key, value)
    return applied


def resolve_profile(
    profile: LaunchProfile | str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProfileContract:
    """Resolve a full :class:`ProfileContract` without mutating the environment."""
    env = os.environ if env is None else env
    resolved = profile if isinstance(profile, LaunchProfile) else parse_profile(profile, strict=False)
    caps = capabilities_for(resolved, env)
    defaults = profile_env_defaults(resolved)
    return ProfileContract(
        profile=resolved,
        description=_DESCRIPTIONS[resolved],
        capabilities=caps,
        env_defaults=defaults,
        preferred_port=PREFERRED_PORTS[resolved],
        ai_mode_default=defaults.get("PIS_AI_MODE", "auto"),
    )


#: Module-level registry mirroring :class:`LaunchProfile` for callers that want
#: to iterate contracts without resolving the environment.
PROFILES: dict[LaunchProfile, ProfileContract] = {
    profile: resolve_profile(profile, env={}) for profile in LaunchProfile
}
