"""Persistent named-entity extraction (M015).

Structured types (EMAIL/URL/PHONE/IP/IBAN/CARD/DATE/MONEY) are deterministic
regex + validation and reported at high confidence. PERSON/ORGANIZATION/
LOCATION use conservative heuristics (title prefixes, legal suffixes, a small
gazetteer) and are explicitly marked low-confidence — they are never presented
as reliable. PII-typed entities persist a masked display + salted fingerprint.
"""
from __future__ import annotations

import re
from typing import Any

from . import pii as pii_mod

_ORG_RE = re.compile(
    r"\b([A-ZÀ-ÖØ-Þ][\w&'.\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\w&'.\-]*){0,3}\s+"
    r"(?:GmbH|AG|SARL|SAS|SASU|SA|EURL|SCI|SNC|Inc\.?|Ltd\.?|LLC|PLC|Corp\.?|Company|Bank|Versicherung|Assurance))")
_LOC_GAZETTEER = {
    "paris", "berlin", "toulouse", "lyon", "marseille", "madrid", "london", "munich",
    "münchen", "hamburg", "frankfurt", "köln", "wien", "zürich", "geneva", "genève",
    "france", "germany", "deutschland", "spain", "italy", "belgium", "luxembourg",
    "bordeaux", "nantes", "strasbourg", "stuttgart", "karlsruhe",
}
_MONEY_RE = re.compile(
    r"(?:[€$£]\s?\d[\d .,]*|\b(?:EUR|USD|GBP|CHF)\s?\d[\d .,]*|\d[\d .,]*\s?(?:€|\$|£|EUR|USD|GBP|CHF))\b")
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|"
    r"januar|februar|märz|april|juni|juli|august|september|oktober|november|dezember|"
    r"january|february|march|june|july|october|december)\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})\b",
    re.IGNORECASE)
_LOC_CONTEXT_RE = re.compile(
    r"\b(?:à|au|aux|en|in|nach|bei|from|de)\s+([A-ZÀ-ÖØ-Þ][\w\-]+(?:\s+[A-ZÀ-ÖØ-Þ][\w\-]+)?)")

# PII-typed structured entities are stored masked+fingerprinted.
_MASK_TYPES = {"EMAIL", "PHONE", "IP", "IBAN", "CARD"}


def extract_entities(text: str, *, store: Any = None) -> list[dict[str, Any]]:
    raw = text or ""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def emit(entity_type: str, normalized: str, display: str, *, confidence: float, method: str) -> None:
        key = (entity_type, normalized)
        if key in seen:
            return
        seen.add(key)
        out.append({"type": entity_type, "normalized": normalized, "display": display,
                    "count": 1, "confidence": confidence, "method": method})

    for f in pii_mod.detect_pii(raw, store=store):
        if f["type"] in {"email", "phone", "ip", "iban", "card"}:
            entity = f["type"].upper()
            emit(entity, f.get("fingerprint") or f["masked"], f["masked"],
                 confidence=f["confidence"], method=f"{f['detector']}+masked")

    for m in pii_mod._URL_RE.finditer(raw):
        emit("URL", m.group(0).rstrip(".,);"), m.group(0), confidence=0.95, method="url")

    for m in _MONEY_RE.finditer(raw):
        emit("MONEY", re.sub(r"\s+", "", m.group(0)), m.group(0).strip(),
             confidence=0.7, method="money_pattern")

    for m in _DATE_RE.finditer(raw):
        emit("DATE", m.group(0).lower(), m.group(0), confidence=0.8, method="date_pattern")

    for m in _ORG_RE.finditer(raw):
        name = m.group(1).strip()
        emit("ORGANIZATION", name.lower(), name, confidence=0.5, method="legal_suffix")

    for m in pii_mod._PERSON_TITLE_RE.finditer(raw):
        name = m.group(1).strip()
        emit("PERSON", name.lower(), pii_mod.mask_name(name), confidence=0.35, method="title_heuristic")

    for m in _LOC_CONTEXT_RE.finditer(raw):
        name = m.group(1).strip()
        if name.lower() in _LOC_GAZETTEER:
            emit("LOCATION", name.lower(), name, confidence=0.6, method="gazetteer_context")
    for m in re.finditer(r"\b([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ\-]{2,})\b", raw):
        if m.group(1).lower() in _LOC_GAZETTEER:
            emit("LOCATION", m.group(1).lower(), m.group(1), confidence=0.4, method="gazetteer")

    return out


RELIABLE_TYPES = {"EMAIL", "URL", "PHONE", "IP", "IBAN", "CARD", "DATE", "MONEY"}
