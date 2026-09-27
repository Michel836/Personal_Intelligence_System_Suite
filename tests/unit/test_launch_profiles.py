"""Launch profile contracts and precedence (M012-B2)."""
from __future__ import annotations

import pytest

from src.core.launch_profile import (
    ADVANCED_CAPABILITIES,
    CORE_CAPABILITIES,
    DEFAULT_PROFILE,
    PREFERRED_PORTS,
    PROFILES,
    Capability,
    LaunchProfile,
    apply_profile_defaults,
    capabilities_for,
    current_profile,
    has_capability,
    parse_profile,
    profile_env_defaults,
    resolve_profile,
)

ALL_CAPABILITIES = CORE_CAPABILITIES | ADVANCED_CAPABILITIES


def test_default_profile_preserves_direct_app_behaviour() -> None:
    assert DEFAULT_PROFILE is LaunchProfile.FULL
    assert parse_profile(None, strict=True) is LaunchProfile.FULL
    assert parse_profile("", strict=True) is LaunchProfile.FULL


def test_parse_profile_accepts_case_and_rejects_unknown_when_strict() -> None:
    assert parse_profile("LITE") is LaunchProfile.LITE
    assert parse_profile("  smart ") is LaunchProfile.SMART
    assert parse_profile("bogus") is DEFAULT_PROFILE
    with pytest.raises(ValueError):
        parse_profile("bogus", strict=True)


def test_current_profile_reads_env() -> None:
    assert current_profile({"PIS_LAUNCH_PROFILE": "lite"}) is LaunchProfile.LITE
    assert current_profile({}) is DEFAULT_PROFILE


def test_capability_sets_match_product_intent() -> None:
    lite = capabilities_for(LaunchProfile.LITE, {})
    assert lite >= CORE_CAPABILITIES
    assert not (ADVANCED_CAPABILITIES & lite)
    for profile in (LaunchProfile.SMART, LaunchProfile.FULL):
        assert capabilities_for(profile, {}) == ALL_CAPABILITIES


def test_core_capabilities_cannot_be_disabled() -> None:
    caps = capabilities_for(LaunchProfile.FULL, {"PIS_FEATURE_SEARCH": "0", "PIS_FEATURE_SCAN": "0"})
    assert Capability.SEARCH in caps and Capability.SCAN in caps


def test_advanced_capabilities_can_be_toggled() -> None:
    lite_on = capabilities_for(LaunchProfile.LITE, {"PIS_FEATURE_AI_CHAT": "1"})
    assert Capability.AI_CHAT in lite_on
    full_off = capabilities_for(LaunchProfile.FULL, {"PIS_FEATURE_VISUALIZATIONS": "0"})
    assert Capability.VISUALIZATIONS not in full_off
    assert Capability.SEARCH in full_off


def test_has_capability_helper() -> None:
    assert has_capability(Capability.SEARCH, LaunchProfile.LITE, {})
    assert not has_capability(Capability.AI_CHAT, LaunchProfile.LITE, {})
    assert has_capability(Capability.AI_CHAT, LaunchProfile.LITE, {"PIS_FEATURE_AI_CHAT": "true"})


def test_profile_env_defaults_are_privacy_safe() -> None:
    for profile in LaunchProfile:
        defaults = profile_env_defaults(profile)
        assert defaults["PIS_REMOTE_CONTENT_POLICY"] == "never"
        # Heavy preload is off in every profile: startup stays lazy.
        assert defaults["PIS_HEAVY_PRELOAD"] == "0"
    assert profile_env_defaults(LaunchProfile.LITE)["PIS_AI_MODE"] == "local"
    assert profile_env_defaults(LaunchProfile.SMART)["PIS_AI_MODE"] == "auto"
    assert profile_env_defaults(LaunchProfile.FULL)["PIS_AI_MODE"] == "auto"


def test_apply_profile_defaults_never_overrides_explicit_env() -> None:
    env = {
        "PIS_AI_MODE": "hybrid",
        "PIS_REMOTE_CONTENT_POLICY": "extracted_text",
        "PIS_EMBEDDING_BACKEND": "openai_compatible",
    }
    applied = apply_profile_defaults(LaunchProfile.LITE, env)
    assert env["PIS_AI_MODE"] == "hybrid"
    assert env["PIS_REMOTE_CONTENT_POLICY"] == "extracted_text"
    assert env["PIS_EMBEDDING_BACKEND"] == "openai_compatible"
    assert "PIS_AI_MODE" not in applied
    assert "PIS_REMOTE_CONTENT_POLICY" not in applied
    # Defaults that were absent are filled.
    assert env["PIS_HEAVY_PRELOAD"] == "0"
    assert env["PIS_LAUNCH_PROFILE"] == "lite"


def test_apply_profile_defaults_treats_blank_as_unset() -> None:
    env = {"PIS_AI_MODE": "   "}
    apply_profile_defaults(LaunchProfile.LITE, env)
    assert env["PIS_AI_MODE"] == "local"


def test_resolve_profile_contracts() -> None:
    for profile in LaunchProfile:
        contract = resolve_profile(profile, {})
        assert contract.profile is profile
        assert contract.preferred_port == PREFERRED_PORTS[profile]
        assert contract.capabilities
        assert contract.as_dict()["profile"] == profile.value
    assert PROFILES[LaunchProfile.LITE].profile is LaunchProfile.LITE
