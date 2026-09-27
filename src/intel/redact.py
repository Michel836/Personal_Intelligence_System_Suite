"""Non-destructive PII redaction preview (M015).

Produces a masked derivative in memory for display/export. It never reads or
writes the original source file and never persists the unmasked text.
"""
from __future__ import annotations

import re
from typing import Any

from . import pii as pii_mod


def _mask_with(pattern: re.Pattern[str], text: str, masker: Any, *, validate: Any = None) -> str:
    def repl(m: re.Match[str]) -> str:
        value = m.group(0)
        if validate is not None and not validate(value):
            return value
        return str(masker(value))
    return str(pattern.sub(repl, text))


def redact_text(text: str) -> str:
    """Return a masked copy of ``text`` (no offsets stored, regex re-applied)."""
    out = text or ""
    out = _mask_with(pii_mod._EMAIL_RE, out, pii_mod.mask_email)
    out = _mask_with(pii_mod._IBAN_RE, out, pii_mod.mask_iban, validate=pii_mod.iban_ok)
    out = _mask_with(pii_mod._CARD_RE, out, pii_mod.mask_card, validate=pii_mod.luhn_ok)
    out = _mask_with(pii_mod._IPV4_RE, out, pii_mod.mask_ip)
    out = _mask_with(pii_mod._IPV6_RE, out, pii_mod.mask_ip)
    phone_validate = lambda v: 8 <= len(re.sub(r"\D", "", v)) <= 15  # noqa: E731
    for pattern in (pii_mod._PHONE_INTL_RE, pii_mod._PHONE_FR_RE, pii_mod._PHONE_DE_RE):
        out = _mask_with(pattern, out, pii_mod.mask_phone, validate=phone_validate)
    return _mask_with(pii_mod._NIR_RE, out, lambda _v: "***", validate=pii_mod.nir_ok)


def redacted_preview(text: str, *, store: Any = None, max_chars: int = 4000) -> dict[str, Any]:
    """Return a bounded masked preview plus the masked findings summary."""
    snippet = (text or "")[:max_chars]
    findings = pii_mod.detect_pii(snippet, store=store)
    return {"redacted": redact_text(snippet), "findings": findings,
            "truncated": len(text or "") > max_chars, "chars": len(snippet)}
