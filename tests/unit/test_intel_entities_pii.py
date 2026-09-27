"""Entity + PII detection quality and false-positive controls (M015)."""
from __future__ import annotations

from src.intel import detect_pii, extract_entities, is_sensitive


class _Store:
    def fingerprint(self, value: str) -> str:
        import hashlib
        return hashlib.blake2b(value.encode(), digest_size=8).hexdigest()


def _types(text):
    return {f["type"] for f in detect_pii(text, store=_Store())}


def test_email_phone_ip_url() -> None:
    text = ("Contact jean.dupont@example.com or +33 6 12 34 56 78, "
            "site https://example.org/page, host 10.20.30.40.")
    types = _types(text)
    assert {"email", "phone", "ip"} <= types
    entities = {e["type"] for e in extract_entities(text, store=_Store())}
    assert {"EMAIL", "PHONE", "IP", "URL"} <= entities


def test_iban_and_card_validation() -> None:
    valid_iban = "FR76 3000 6000 0112 3456 7890 189"
    invalid_iban = "FR76 3000 6000 0112 3456 7890 188"  # wrong check digits
    assert "iban" in _types(valid_iban)
    assert "iban" not in _types(invalid_iban)
    assert "card" in _types("payment card 4111 1111 1111 1111")
    assert "card" not in _types("reference 4111 1111 1111 1112")  # fails Luhn


def test_conservative_negatives() -> None:
    # Random digits, UUIDs, git hashes, dates, invoice numbers must NOT be PII.
    for text in [
        "order 9876543210123456789",
        "uuid 550e8400-e29b-41d4-a716-446655440000",
        "commit a94a8fe5ccb19ba61c4c0873d391e987982fbbd3",
        "date 2026-09-27 and 27/09/2026",
        "invoice 2026-000123",
        "version 3.14.159 failed with code 500",
    ]:
        types = _types(text)
        assert not ({"iban", "card", "national_id"} & types), (text, types)


def test_nir_checksum() -> None:
    # Synthetic NIR with a valid key.
    base = "1800775801001"
    key = 97 - (int(base) % 97)
    valid = f"{base}{key:02d}"
    assert "national_id" in _types(valid)
    bad = f"{base}{(key + 1) % 100:02d}"
    assert "national_id" not in _types(bad)


def test_masking_never_reveals_full_value() -> None:
    text = "mail secret.person@example.com phone +33 6 98 76 54 32"
    for f in detect_pii(text, store=_Store()):
        if f["type"] == "email":
            assert "secret.person" not in f["masked"]
        assert f["masked"] != f"{text}"


def test_severity_classification() -> None:
    iban = list(detect_pii("FR76 3000 6000 0112 3456 7890 189", store=_Store()))
    assert any(f["severity"] == "high" for f in iban)
    assert is_sensitive(iban, min_severity="high")
    assert not is_sensitive([{"type": "ip", "severity": "low"}], min_severity="medium")


def test_redaction_preview_does_not_touch_source() -> None:
    from src.intel import redact_text
    original = "reach me at a.b@c.com or +49 30 12345678"
    masked = redact_text(original)
    assert "a.b@c.com" not in masked
    assert original == "reach me at a.b@c.com or +49 30 12345678"  # unchanged
