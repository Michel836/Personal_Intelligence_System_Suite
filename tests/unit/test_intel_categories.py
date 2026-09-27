"""Categorisation contract + manual-override precedence (M015)."""
from __future__ import annotations

from src.intel.categories import CategoryEngine


def test_structural_and_topic_categories() -> None:
    engine = CategoryEngine()
    invoice = ("Facture Free du mois, montant 29,99 EUR, prélèvement bancaire. "
               "Rechnung und Zahlung per Bankkonto.")
    cats = {c["category"] for c in engine.classify(invoice, extension=".pdf")}
    assert "document_pdf" in cats
    assert "finance" in cats

    legal = "Le tribunal a rendu un jugement; l'avocat dépose des conclusions."
    cats2 = {c["category"] for c in engine.classify(legal, extension=".docx")}
    assert "legal" in cats2

    code = engine.classify("def f(): return 1", extension=".py")
    assert any(c["category"] == "source_code" and c["source"] == "structural" for c in code)


def test_custom_category() -> None:
    engine = CategoryEngine()
    engine.add_category("astronomy", ["telescope", "nebula", "galaxy"])
    cats = {c["category"] for c in engine.classify("The telescope observed a distant galaxy nebula.")}
    assert "astronomy" in cats


def test_empty_text_has_no_topic_category() -> None:
    engine = CategoryEngine()
    assert engine.classify("", extension=".txt") == [
        {"category": "text", "score": 1.0, "source": "structural"}]
