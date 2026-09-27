"""Local text/topic-feature unit tests (M020)."""
from __future__ import annotations

from collections import Counter

from src.galaxy.text import ctfidf_terms, is_safe_term, tfidf_terms, tokenize
from src.galaxy.topics import label_from_evidence


def test_tokenize_drops_stopwords_short_and_numbers() -> None:
    tokens = tokenize("The invoice 12345 is for the bank and a x")
    assert "invoice" in tokens and "bank" in tokens
    assert "the" not in tokens
    assert "12345" not in tokens
    assert "x" not in tokens


def test_tokenize_is_bounded() -> None:
    tokens = tokenize("alpha " * 5000, max_tokens=50)
    assert len(tokens) == 50


def test_is_safe_term_rejects_pii_shapes() -> None:
    assert is_safe_term("finance") is True
    assert is_safe_term("jean.dupont@example.com") is False
    assert is_safe_term("/private/path/file") is False
    assert is_safe_term("123456789") is False
    assert is_safe_term("ab") is False


def test_ctfidf_favours_cluster_specific_terms() -> None:
    clusters = {
        0: Counter({"invoice": 10, "bank": 8, "common": 5}),
        1: Counter({"compiler": 10, "python": 8, "common": 5}),
    }
    global_counts = Counter()
    for counts in clusters.values():
        global_counts.update(counts)
    weights = ctfidf_terms(clusters, global_counts, top_k=2)
    assert weights[0][0][0] == "invoice"
    assert weights[1][0][0] == "compiler"


def test_tfidf_terms_bounded() -> None:
    tokens = tokenize("finance finance bank audit audit audit revenue")
    terms = tfidf_terms(tokens, n_docs=2, top_k=2)
    assert len(terms) == 2
    assert terms[0][0] == "audit"


def test_label_from_evidence_masks_pii_and_prefers_terms() -> None:
    label = label_from_evidence(
        [("jean.dupont@example.com", 9.0), ("finance", 2.0), ("invoice", 1.0)],
        [{"type": "EMAIL", "display": "j***@example.com"}, {"type": "ORGANIZATION", "display": "Acme"}],
        [{"category": "finance"}], 4)
    assert "finance" in label
    assert "@" not in label
    assert "jean" not in label.lower()


def test_label_falls_back_to_category() -> None:
    label = label_from_evidence([], [], [{"category": "legal"}], 3)
    assert "legal" in label
