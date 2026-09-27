"""Duplicate-aware reranking / fusion for search.

Transparent reciprocal-rank fusion (RRF) of lexical and semantic results, with
an exact filename/path relevance boost, optional exact-duplicate collapse and
version-family diversity. Lexical ordering is preserved when the semantic engine
is unavailable, so the lexical fallback never regresses.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _exact_hit(result: dict[str, Any], query_tokens: list[str]) -> bool:
    if not query_tokens:
        return False
    hay = (result.get("filename") or "") + " " + (result.get("path") or "")
    hay = hay.lower()
    return all(t in hay for t in query_tokens)


def fuse_results(lexical: Iterable[dict[str, Any]], semantic: Iterable[dict[str, Any]], *,
                 limit: int = 20, k: int = 60, w_lex: float = 1.0, w_sem: float = 1.0,
                 query: str = "", collapse_duplicates: bool = True,
                 version_diversity: bool = False, dedup_store: Any = None,
                 show_all_copies: bool = False,
                 show_all_versions: bool = False) -> list[dict[str, Any]]:
    """Fuse lexical + semantic rankings into one transparent, deduplicated list."""
    lex_list = list(lexical)
    sem_list = list(semantic)
    query_tokens = _tokens(query)

    merged: dict[int, dict[str, Any]] = {}
    for rank, doc in enumerate(lex_list, start=1):
        fid = int(doc["id"])
        entry = merged.setdefault(fid, dict(doc))
        entry["lexical_rank"] = rank
    for rank, doc in enumerate(sem_list, start=1):
        fid = int(doc["id"])
        entry = merged.setdefault(fid, dict(doc))
        entry["semantic_rank"] = rank
    if not merged:
        return []

    for entry in merged.values():
        score = 0.0
        if entry.get("lexical_rank"):
            score += w_lex / (k + entry["lexical_rank"])
        if entry.get("semantic_rank"):
            score += w_sem / (k + entry["semantic_rank"])
        if _exact_hit(entry, query_tokens):
            score += 0.5  # never let fusion bury an exact filename/path hit
            entry["exact_title_boost"] = True
        entry["fusion_score"] = round(score, 8)
        entry.setdefault("search_type", "semantic" if entry.get("semantic_rank") else "lexical")

    ranked = sorted(merged.values(),
                    key=lambda d: (-d["fusion_score"], d.get("lexical_rank") or 10**9,
                                   d.get("semantic_rank") or 10**9, int(d["id"])))

    digest_by_id: dict[int, str] = {}
    family_by_id: dict[int, int] = {}
    if dedup_store is not None and (collapse_duplicates or version_diversity):
        ids = [int(d["id"]) for d in ranked]
        if ids:
            ph = ",".join("?" * len(ids))
            with dedup_store.db.get_connection() as conn:
                for fid, digest in conn.execute(
                        f"SELECT file_id, digest FROM content_hashes WHERE file_id IN ({ph})", ids):
                    digest_by_id[int(fid)] = digest
                for fid, fam in conn.execute(
                        f"SELECT file_id, family_id FROM version_members WHERE file_id IN ({ph})", ids):
                    family_by_id[int(fid)] = int(fam)

    out: list[dict[str, Any]] = []
    seen_digest: dict[str, int] = {}
    seen_family: dict[int, int] = {}
    for entry in ranked:
        fid = int(entry["id"])
        if collapse_duplicates and not show_all_copies:
            digest = digest_by_id.get(fid)
            if digest:
                if digest in seen_digest:
                    seen_digest[digest] += 1
                    continue
                seen_digest[digest] = 1
        if version_diversity and not show_all_versions:
            fam = family_by_id.get(fid)
            if fam is not None:
                if fam in seen_family:
                    seen_family[fam] += 1
                    continue
                seen_family[fam] = 1
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def rerank_search(db: Any, semantic_engine: Any, query: str, *, limit: int = 20,
                  candidate_multiplier: int = 3, dedup_store: Any = None,
                  collapse_duplicates: bool = True, version_diversity: bool = False,
                  semantic_weight: float = 1.0, lexical_weight: float = 1.0,
                  **filters: Any) -> list[dict[str, Any]]:
    """Retrieve lexical + semantic candidates and fuse them."""
    n = max(limit * candidate_multiplier, limit + 10)
    lexical = db.search_files(query=query, limit=n, **filters)
    semantic: list[dict[str, Any]] = []
    if semantic_engine is not None:
        try:
            if semantic_engine.is_available():
                semantic = semantic_engine.semantic_search(query, limit=n, similarity_threshold=0.0)
        except Exception:  # noqa: BLE001 - fall back to lexical ordering
            semantic = []
    return fuse_results(lexical, semantic, limit=limit, query=query,
                        w_lex=lexical_weight, w_sem=semantic_weight,
                        collapse_duplicates=collapse_duplicates,
                        version_diversity=version_diversity, dedup_store=dedup_store)
