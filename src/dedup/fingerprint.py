"""Cheap lexical fingerprints for bounded near-duplicate candidate generation."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def shingles(tokens: Sequence[str], k: int = 4) -> list[str]:
    if len(tokens) < k:
        return list(tokens)
    return [" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]


def simhash64(tokens: Sequence[str], *, k: int = 4) -> int:
    """64-bit SimHash over distinct token shingles (deterministic)."""
    vector = [0] * 64
    for shingle in set(shingles(tokens, k)):
        h = int.from_bytes(
            hashlib.blake2b(shingle.encode("utf-8", "ignore"), digest_size=8).digest(), "big"
        )
        for i in range(64):
            vector[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if vector[i] > 0:
            out |= (1 << i)
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def band_keys(value: int, *, bands: int = 4) -> list[int]:
    """Split a 64-bit fingerprint into ``bands`` equal-width LSH keys."""
    width = 64 // bands
    mask = (1 << width) - 1
    return [(value >> (width * i)) & mask for i in range(bands)]


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0
