"""Conservative local PII detection with validation (M015).

Structured identifiers are validated where a standard permits (IBAN mod-97,
payment-card Luhn, IP parsing, FR NIR key). Findings persist only a **masked**
display and a salted fingerprint — never a raw value — and raw values are never
logged. A numeric string is never treated as PII without evidence.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any

SEVERITY = {
    "email": "medium", "phone": "medium", "iban": "high", "card": "high",
    "national_id": "high", "dob": "high", "postal_address": "medium",
    "person_name": "medium", "ip": "low", "account_id": "medium", "url": "low",
}

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b")
_CARD_RE = re.compile(r"(?<![\dA-Za-z])(?:\d[ -]?){13,19}(?![\dA-Za-z])")
# International prefix, or a national FR/DE-style format. Bare digit
# runs are deliberately *not* phones (precision over recall).
_PHONE_INTL_RE = re.compile(r"(?<![\w])(?:\+|00)\d{1,3}(?:[\s.\-]?\d){6,13}(?![\w])")
_PHONE_FR_RE = re.compile(r"(?<!\d)0[1-9](?:[\s.\-]?\d{2}){4}(?!\d)")
_PHONE_DE_RE = re.compile(r"(?<!\d)0\d{2,5}[\s/\-]\d{3,}(?!\d)")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_IPV6_RE = re.compile(r"(?<![:.\w])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}(?![:.\w])")
_NIR_RE = re.compile(r"(?<!\d)([12]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2[AB])\s?\d{3}\s?\d{3})(?:\s?(\d{2}))?(?!\d)")
_ADDRESS_RE = re.compile(
    r"\b\d{1,4}\s+(?:rue|avenue|av\.|boulevard|bd|chemin|impasse|place|straße|strasse|str\.|weg|gasse|platz|road|street|st\.|lane|drive)\b[^\n,;]{0,60}",
    re.IGNORECASE)
_PLZ_CITY_RE = re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß\-]{2,}(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+)?\b")
_DOB_CONTEXT_RE = re.compile(
    r"(?:né(?:e)?\s+le|date\s+de\s+naissance|geboren\s+am|geburtsdatum|born\s+on|date\s+of\s+birth)"
    r"[^\n]{0,20}?(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE)
_PERSON_TITLE_RE = re.compile(
    r"\b(?:M\.|Mme|Mlle|Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?|Herr|Frau)\s+"
    r"([A-ZÀ-ÖØ-Þ][\w'\-]+(?:\s+[A-ZÀ-ÖØ-Þ][\w'\-]+){1,2})")
_ACCOUNT_RE = re.compile(
    r"\b(?:customer|client|kunde|kundennummer|compte|account|contrat|vertrag|dossier)\s*"
    r"(?:n[°o]?|nr\.?|no\.?|#|id)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{4,})", re.IGNORECASE)
_URL_RE = re.compile(r"\bhttps?://[^\s<>\"')]+|\bwww\.[^\s<>\"')]+", re.IGNORECASE)


def luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if len(nums) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(nums)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    compact = re.sub(r"\s+", "", value).upper()
    if not (15 <= len(compact) <= 34) or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    try:
        return int(digits) % 97 == 1
    except ValueError:
        return False


def nir_ok(value: str) -> bool:
    compact = re.sub(r"\s+", "", value).upper()
    if len(compact) != 15:
        return False
    base = compact[:13].replace("2A", "19").replace("2B", "18")
    if not base.isdigit():
        return False
    key = int(compact[13:])
    return (97 - (int(base) % 97)) == key


def mask_email(v: str) -> str:
    local, _, domain = v.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_phone(v: str) -> str:
    digits = re.sub(r"\D", "", v)
    return ("*" * max(0, len(digits) - 2)) + digits[-2:] if digits else "***"


def mask_iban(v: str) -> str:
    c = re.sub(r"\s+", "", v).upper()
    return f"{c[:4]} **** **** {c[-4:]}" if len(c) >= 8 else "****"


def mask_card(v: str) -> str:
    d = re.sub(r"\D", "", v)
    return f"**** **** **** {d[-4:]}" if len(d) >= 4 else "****"


def mask_ip(v: str) -> str:
    if ":" in v:
        parts = v.split(":")
        return ":".join(parts[:2] + ["****"])
    parts = v.split(".")
    return ".".join(parts[:2] + ["*", "*"])


def mask_name(v: str) -> str:
    return v[:1] + "***"


def mask_address(v: str) -> str:
    return v[:8] + "…" if len(v) > 8 else "…"


def mask_dob(v: str) -> str:
    return "**/**/" + (v[-4:] if len(v) >= 4 else "****")


_MASKERS = {
    "email": mask_email, "phone": mask_phone, "iban": mask_iban, "card": mask_card,
    "ip": mask_ip, "person_name": mask_name, "postal_address": mask_address, "dob": mask_dob,
}


def _finding(pii_type: str, value: str, *, confidence: float, detector: str,
             store: Any = None, count: int = 1) -> dict[str, Any]:
    masker = _MASKERS.get(pii_type, lambda _v: "****")
    fingerprint = store.fingerprint(value) if store is not None else None
    return {"type": pii_type, "severity": SEVERITY.get(pii_type, "medium"),
            "count": int(count), "confidence": round(confidence, 3), "detector": detector,
            "fingerprint": fingerprint, "masked": masker(value)}


def detect_pii(text: str, *, store: Any = None) -> list[dict[str, Any]]:
    raw = text or ""
    findings: list[dict[str, Any]] = []

    def collect(matches: Any, pii_type: str, *, key: Any = None, confidence: float = 0.9, detector: str = "regex") -> None:
        seen: dict[str, int] = {}
        for m in matches:
            v = key(m) if key else m.group(0)
            seen[v] = seen.get(v, 0) + 1
        for v, c in seen.items():
            findings.append(_finding(pii_type, v, confidence=confidence,
                                     detector=detector, store=store, count=c))

    collect(_EMAIL_RE.finditer(raw), "email", confidence=0.95, detector="email")
    collect((m for m in _IBAN_RE.finditer(raw) if iban_ok(m.group(0))), "iban",
            confidence=0.95, detector="iban_mod97")
    def _card_ok(m: re.Match[str]) -> bool:
        digits = re.sub(r"\D", "", m.group(0))
        return len(digits) in (15, 16) and digits[0] in "3456" and luhn_ok(digits)
    collect((m for m in _CARD_RE.finditer(raw) if _card_ok(m)), "card",
            confidence=0.9, detector="luhn_issuer")

    phones = []
    seen_phone_spans: set[tuple[int, int]] = set()
    for pattern in (_PHONE_INTL_RE, _PHONE_FR_RE, _PHONE_DE_RE):
        for m in pattern.finditer(raw):
            if (m.start(), m.end()) in seen_phone_spans:
                continue
            v = m.group(0)
            if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", v):
                continue  # IPv4, not a phone
            digits = re.sub(r"\D", "", v)
            if 8 <= len(digits) <= 15:
                phones.append(m)
                seen_phone_spans.add((m.start(), m.end()))
    collect(phones, "phone", confidence=0.7, detector="phone_format")

    ips = []
    for m in list(_IPV4_RE.finditer(raw)) + list(_IPV6_RE.finditer(raw)):
        try:
            ipaddress.ip_address(m.group(0))
            ips.append(m)
        except ValueError:
            pass
    collect(ips, "ip", confidence=0.85, detector="ipaddress")

    collect((m for m in _NIR_RE.finditer(raw) if m.group(2) and nir_ok(m.group(0))),
            "national_id", confidence=0.9, detector="nir_mod97")

    collect(_ADDRESS_RE.finditer(raw), "postal_address", confidence=0.55, detector="address_pattern")
    collect(_PLZ_CITY_RE.finditer(raw), "postal_address", confidence=0.4, detector="plz_city")
    collect(_DOB_CONTEXT_RE.finditer(raw), "dob", key=lambda m: m.group(1),
            confidence=0.7, detector="dob_context")
    collect((m for m in _ACCOUNT_RE.finditer(raw)
             if sum(c.isdigit() for c in m.group(1)) >= 2),
            "account_id", key=lambda m: m.group(1), confidence=0.4, detector="account_context")
    collect(_PERSON_TITLE_RE.finditer(raw), "person_name", key=lambda m: m.group(1),
            confidence=0.35, detector="title_heuristic")

    return findings


def is_sensitive(findings: list[dict[str, Any]], *, min_severity: str = "medium") -> bool:
    order = {"low": 0, "medium": 1, "high": 2}
    threshold = order.get(min_severity, 1)
    return any(order.get(f.get("severity", "medium"), 0) >= threshold for f in findings)
