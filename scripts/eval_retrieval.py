#!/usr/bin/env python3
"""Bounded retrieval-quality harness (M009H.5).

Builds a local evaluation set from an indexed database (no labels are committed)
and compares embedding models on Recall@5/@10 and MRR.

Usage::

    python scripts/eval_retrieval.py --db /path/to/files.db --model bge-m3 --model multilingual-e5-base

Queries are generated locally from distinctive terms in each document so the
ground truth is term-based lexical relevance; results are printed, never stored
in the repository. Only the harness is committed.
"""
from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path

import numpy as np

from src.core.database import DatabaseManager
from src.intelligence.embeddings import EmbeddingGenerator, resolve_model_key

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]{8,}")


def _load_documents(db_path: str, max_docs: int):
    db = DatabaseManager(db_path)
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, content_text FROM files
               WHERE content_extracted = 1 AND content_text IS NOT NULL
                 AND length(content_text) BETWEEN 80 AND 4000
               ORDER BY id LIMIT ?""",
            (max_docs,),
        ).fetchall()
    return [(int(r["id"]), r["content_text"]) for r in rows]


def _build_queries(docs, max_queries: int):
    """Term-based queries with lexical ground truth (objective, local)."""
    token_to_docs: dict[str, set[int]] = {}
    for doc_id, text in docs:
        for token in set(_TOKEN_RE.findall(text.lower())):
            token_to_docs.setdefault(token, set()).add(doc_id)
    # keep terms that match a small, non-trivial set of documents
    queries = [
        (token, ids)
        for token, ids in token_to_docs.items()
        if 1 <= len(ids) <= max(2, len(docs) // 10)
    ]
    queries.sort()
    return queries[:max_queries]


def _evaluate(model_key: str, docs, queries, db_path: str) -> dict:
    import torch

    os.environ["PIS_EMBEDDING_MODEL"] = model_key
    gen = EmbeddingGenerator(model_key)
    if not gen.is_available():
        return {"model": model_key, "error": "unavailable"}

    texts = [t for _, t in docs]
    t0 = time.perf_counter()
    doc_emb = gen.generate_batch_embeddings(texts, batch_size=64, show_progress=False)
    embed_s = time.perf_counter() - t0
    dim = gen.embedding_dim

    valid = [(i, e) for i, e in enumerate(doc_emb) if e is not None]
    doc_vecs = [e for _, e in valid]
    doc_ids = [docs[i][0] for i, _ in valid]

    recalls_5, recalls_10, rrs = [], [], []
    t0 = time.perf_counter()
    for token, relevant in queries:
        q = gen.generate_embedding(token)
        if q is None:
            continue
        ranked = gen.find_similar(q, doc_vecs, top_k=10)
        ids = [doc_ids[i] for i, _ in ranked]
        hit5 = len(set(ids[:5]) & relevant)
        hit10 = len(set(ids[:10]) & relevant)
        recalls_5.append(hit5 / len(relevant))
        recalls_10.append(hit10 / len(relevant))
        rr = 0.0
        for rank, doc_id in enumerate(ids, 1):
            if doc_id in relevant:
                rr = 1.0 / rank
                break
        rrs.append(rr)
    query_ms = (time.perf_counter() - t0) / max(len(queries), 1) * 1000
    vram = torch.cuda.max_memory_allocated() / 1e9 if torch.cuda.is_available() else 0.0

    return {
        "model": model_key,
        "dim": dim,
        "docs": len(valid),
        "queries": len(recalls_5),
        "recall@5": float(np.mean(recalls_5)) if recalls_5 else 0.0,
        "recall@10": float(np.mean(recalls_10)) if recalls_10 else 0.0,
        "mrr": float(np.mean(rrs)) if rrs else 0.0,
        "embed_s": embed_s,
        "embed_per_s": len(valid) / max(embed_s, 1e-9),
        "query_ms": query_ms,
        "storage_mb": (len(valid) * (dim or 0) * 4) / 1e6,
        "vram_gb": vram,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--max-docs", type=int, default=1500)
    parser.add_argument("--max-queries", type=int, default=100)
    args = parser.parse_args()

    docs = _load_documents(args.db, args.max_docs)
    queries = _build_queries(docs, args.max_queries)
    print(f"docs={len(docs)} queries={len(queries)}")
    for model in args.model:
        resolve_model_key(model)  # validate
        metrics = _evaluate(model, docs, queries, args.db)
        print(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
