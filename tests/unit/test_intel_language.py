"""Deterministic language-detection benchmark (M015)."""
from __future__ import annotations

from src.intel import detect_language

SAMPLES = {
    "fr": [
        "Le contrat de service entre la société et le client prévoit une facture mensuelle et un préavis.",
        "La recherche d'emploi demande de préparer un curriculum vitae et une lettre de motivation.",
        "Le tribunal a rendu son jugement après avoir entendu les avocats des deux parties.",
    ],
    "de": [
        "Der Vertrag zwischen der Gesellschaft und dem Kunden sieht eine monatliche Rechnung vor.",
        "Die Steuererklärung muss bis zum Ende des Monats beim Finanzamt eingereicht werden.",
        "Das Gericht hat nach der Anhörung der Anwälte beider Parteien sein Urteil gefällt.",
    ],
    "en": [
        "The service contract between the company and the client provides for a monthly invoice.",
        "Job search requires preparing a curriculum vitae and a cover letter for each application.",
        "The court delivered its judgment after hearing the lawyers of both parties.",
    ],
    "es": [
        "El contrato de servicio entre la empresa y el cliente prevé una factura mensual.",
        "La declaración de la renta se presenta ante la administración tributaria cada año.",
    ],
    "it": [
        "Il contratto di servizio tra la società e il cliente prevede una fattura mensile.",
        "La dichiarazione dei redditi deve essere presentata ogni anno all'amministrazione.",
    ],
    "pt": [
        "O contrato de serviço entre a empresa e o cliente prevê uma fatura mensal.",
        "A declaração de impostos deve ser apresentada todos os anos à administração.",
    ],
    "nl": [
        "Het contract tussen het bedrijf en de klant voorziet in een maandelijkse factuur.",
        "De belastingaangifte moet ieder jaar bij de belastingdienst worden ingediend.",
    ],
    "ru": ["Договор между компанией и клиентом предусматривает ежемесячный счёт и оплату."],
    "ar": ["يحدد العقد بين الشركة والعميل فاتورة شهرية ودفعا منتظما."],
}


def test_priority_languages_correct() -> None:
    for lang, samples in SAMPLES.items():
        for text in samples:
            result = detect_language(text)
            assert result["lang"] == lang, (lang, result)
            assert result["status"] == "OK"
            assert 0.0 < result["confidence"] <= 1.0


def test_short_and_empty_are_not_confident() -> None:
    assert detect_language("")["status"] == "INSUFFICIENT_TEXT"
    assert detect_language("bonjour")["status"] in {"INSUFFICIENT_TEXT", "UNKNOWN"}
    assert detect_language("ok")["lang"] == "und"


def test_code_is_not_natural_language() -> None:
    code = "def compute(x):\n    import os\n    return os.path.join(x, 'y')\n" * 3
    assert detect_language(code)["status"] == "CODE"


def test_mixed_language_reports_primary() -> None:
    mixed = ("Le contrat de service prévoit une facture mensuelle pour le client. " * 3
             + "Der Vertrag zwischen der Gesellschaft und dem Kunden sieht eine Rechnung vor. " * 3)
    result = detect_language(mixed)
    assert result["lang"] in {"fr", "de"}
    assert result["status"] == "OK"
    assert result["mixed"]
