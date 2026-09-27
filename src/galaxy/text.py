"""Dependency-light local text features for topic representation (M020).

Deterministic tokenization plus TF-IDF and cluster-level c-TF-IDF. No external
NLP dependency is required, nothing is sent off the machine, and the tokenizer
is intentionally simple so topic labels remain explainable and reproducible.

This module is *representation*, not modelling: a "topic" is a human-readable
description derived from cluster/content evidence (top weighted terms, entities,
categories and representative documents). It never claims ground truth.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

#: Unicode word runs of at least three characters (avoids "de", "la", "of"...).
_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]{3,}", re.UNICODE)
#: Pure numeric runs are dropped: numbers are poor topic terms and can leak IDs.
_NUMERIC_RE = re.compile(r"^\d+$")
#: Terms containing these characters are dropped from labels (PII-like shapes).
_PII_SHAPE_RE = re.compile(r"[@/:\\]|^\d{2,}")

#: Short, deliberately conservative multilingual stopword list (EN/FR/DE plus a
#: few common glue words). Weighting — not this list — is what removes
#: boilerplate; keeping it small avoids discarding meaningful domain terms.
STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
    "its", "may", "new", "now", "old", "see", "two", "way", "who", "boy", "did",
    "use", "she", "too", "that", "with", "have", "this", "will", "your", "from",
    "they", "know", "want", "been", "good", "much", "some", "time", "very",
    "when", "come", "here", "just", "like", "long", "make", "many", "more",
    "only", "over", "such", "take", "than", "them", "well", "were", "what",
    "would", "there", "their", "about", "which", "these", "other", "into",
    "could", "should", "also", "after", "before", "between", "because",
    "les", "des", "une", "que", "qui", "dans", "pour", "avec", "sur", "pas",
    "par", "plus", "est", "sont", "aux", "cette", "cet", "ses", "son", "sa",
    "nous", "vous", "ils", "elles", "mais", "ou", "et", "en", "du", "au",
    "der", "die", "das", "und", "ist", "sind", "mit", "von", "den", "dem",
    "ein", "eine", "einer", "eines", "auf", "für", "als", "bei", "nach",
    "nicht", "auch", "werden", "wird", "wurde", "sich", "aus", "im",
    "zum", "zur", "über", "durch", "dass", "man", "kann", "oder",
    "http", "https", "www", "com", "org", "net", "pdf", "doc", "page",
})


def tokenize(text: str | None, *, max_tokens: int = 4000) -> list[str]:
    """Return deterministic, lowercase, stopword-filtered tokens.

    ``max_tokens`` bounds the work per document so a single huge file cannot
    dominate topic extraction. Pure numbers and very short runs are dropped.
    """
    if not text:
        return []
    out: list[str] = []
    for match in _WORD_RE.finditer(text.lower()):
        token = match.group(0)
        if len(token) < 3 or _NUMERIC_RE.match(token) or token in STOPWORDS:
            continue
        out.append(token)
        if len(out) >= max_tokens:
            break
    return out


def is_safe_term(term: str) -> bool:
    """Whether a term is acceptable in a human-readable topic label.

    Rejects PII-shaped tokens (emails, paths, URLs, long numeric runs) so a
    representative text fragment can never leak an identifier into a label.
    """
    if not term or len(term) < 3 or len(term) > 40:
        return False
    if _NUMERIC_RE.match(term) or _PII_SHAPE_RE.search(term):
        return False
    return True


def term_counts(tokens: Iterable[str]) -> Counter[str]:
    return Counter(t for t in tokens if is_safe_term(t))


def tfidf_terms(
    tokens: Sequence[str],
    *,
    global_df: dict[str, int] | None = None,
    n_docs: int = 1,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """Bounded TF-IDF terms for a single document/cluster text blob."""
    counts = term_counts(tokens)
    if not counts:
        return []
    total = sum(counts.values())
    n = max(int(n_docs), 1)
    scored: list[tuple[str, float]] = []
    for term, freq in counts.items():
        tf = freq / total
        df = int((global_df or {}).get(term, 0))
        idf = math.log((1.0 + n) / (1.0 + df)) + 1.0
        scored.append((term, tf * idf))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored[: max(0, int(top_k))]


def ctfidf_terms(
    cluster_counts: dict[int, Counter[str]],
    global_counts: Counter[str],
    *,
    total_terms: int | None = None,
    top_k: int = 12,
) -> dict[int, list[tuple[str, float]]]:
    """Class-based TF-IDF (c-TF-IDF) over clusters.

    ``score(t, c) = tf(t, c) * log(1 + A / f(t))`` where ``A`` is the mean number
    of terms per cluster and ``f(t)`` the global term frequency. This favours
    terms that are frequent *within* a cluster but not globally, which is what
    makes cluster labels readable without an external model.
    """
    n_clusters = max(len(cluster_counts), 1)
    if total_terms is None:
        total_terms = sum(sum(c.values()) for c in cluster_counts.values())
    mean_terms = max(total_terms / n_clusters, 1.0)
    out: dict[int, list[tuple[str, float]]] = {}
    for cid, counts in cluster_counts.items():
        total = sum(counts.values())
        if not total:
            out[cid] = []
            continue
        scored: list[tuple[str, float]] = []
        for term, freq in counts.items():
            global_freq = int(global_counts.get(term, 0))
            weight = math.log(1.0 + mean_terms / max(global_freq, 1))
            scored.append((term, (freq / total) * weight))
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        out[cid] = scored[: max(0, int(top_k))]
    return out
