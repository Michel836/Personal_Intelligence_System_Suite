"""Canonical extraction outcome taxonomy + retry eligibility (M017)."""
from __future__ import annotations

from enum import Enum


class Outcome(str, Enum):
    EXTRACTED = "EXTRACTED"
    NO_TEXT = "NO_TEXT"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNSUPPORTED_DEPENDENCY = "UNSUPPORTED_DEPENDENCY"
    MALFORMED = "MALFORMED"
    ENCRYPTED = "ENCRYPTED"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    OCR_REQUIRED = "OCR_REQUIRED"
    OCR_FAILED = "OCR_FAILED"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    PERMANENT_ERROR = "PERMANENT_ERROR"


#: Terminal outcomes are not retried unless the content/version changes.
TERMINAL = {
    Outcome.EXTRACTED.value, Outcome.NO_TEXT.value, Outcome.UNSUPPORTED_FORMAT.value,
    Outcome.MALFORMED.value, Outcome.ENCRYPTED.value, Outcome.PASSWORD_REQUIRED.value,
    Outcome.RESOURCE_LIMIT.value, Outcome.PERMANENT_ERROR.value,
}
#: Retryable outcomes (bounded, with backoff).
RETRYABLE = {
    Outcome.TIMEOUT.value, Outcome.TRANSIENT_ERROR.value,
    Outcome.UNSUPPORTED_DEPENDENCY.value, Outcome.OCR_FAILED.value,
}

MAX_ATTEMPTS = 3

_HINTS = {
    Outcome.TIMEOUT.value: ("timed out", "timeout"),
    Outcome.ENCRYPTED.value: ("encrypted", "password required", "is encrypted"),
    Outcome.PASSWORD_REQUIRED.value: ("password", "locked"),
    Outcome.MALFORMED.value: ("corrupt", "malformed", "cannot", "invalid", "damaged", "bad "),
    Outcome.UNSUPPORTED_DEPENDENCY.value: ("dependency", "not installed", "unavailable", "no backend",
                                           "missing"),
    Outcome.UNSUPPORTED_FORMAT.value: ("no suitable extractor", "unsupported", "not supported"),
    Outcome.RESOURCE_LIMIT.value: ("too large", "exceeds", "limit"),
    Outcome.NO_TEXT.value: ("no text", "empty"),
}


def classify_error(error: str | None) -> str:
    """Map an extractor error string to a taxonomy outcome (deterministic)."""
    if not error:
        return Outcome.PERMANENT_ERROR.value
    low = error.lower()
    for outcome, hints in _HINTS.items():
        if any(h in low for h in hints):
            return outcome
    return Outcome.PERMANENT_ERROR.value


def is_terminal(outcome: str) -> bool:
    return outcome in TERMINAL


def is_retryable(outcome: str, *, attempts: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    return outcome in RETRYABLE and attempts < max_attempts


def backoff_seconds(attempts: int) -> int:
    """Bounded exponential backoff: 60s, 300s, 1500s, capped at 1h."""
    return int(min(3600, 60 * (5 ** max(0, attempts - 1))))
