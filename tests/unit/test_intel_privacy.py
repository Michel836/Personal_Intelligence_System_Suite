"""PII vs remote-content policy interaction (M015)."""
from __future__ import annotations

from src.ai.providers.policy import RemoteContentPolicy
from src.intel import detect_pii, remote_warning
from src.intel.privacy import remote_policy_state


class _Store:
    def fingerprint(self, _value: str) -> str:
        return "fp"


def test_never_policy_never_warns_and_is_authoritative() -> None:
    policy = RemoteContentPolicy.NEVER
    findings = detect_pii("mail a@b.com IBAN FR76 3000 6000 0112 3456 7890 189", store=_Store())
    assert remote_warning(policy, findings) is None
    assert remote_policy_state(policy)["allows_remote"] is False
    assert policy.value == "never"  # PII metadata cannot relax the policy


def test_explicit_remote_with_pii_warns_but_does_not_change_policy() -> None:
    policy = RemoteContentPolicy.EXTRACTED_TEXT
    findings = detect_pii("reach a@b.com", store=_Store())
    warning = remote_warning(policy, findings)
    assert warning and "sensitive" in warning.lower()
    assert policy.value == "extracted_text"
    assert policy.allows_extracted_text


def test_no_pii_no_warning() -> None:
    policy = RemoteContentPolicy.FULL_CONTEXT
    assert remote_warning(policy, detect_pii("just a normal sentence about weather", store=_Store())) is None
