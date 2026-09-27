#!/usr/bin/env python3
"""M014 duplicate/near-duplicate/version/related/rerank benchmark.

Read-only on source files; writes only the dedup tables in the target DB.
Reports aggregate metrics only (never private filenames).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO = "/home/chu/Projects/Personal_Intelligence_System_Suite"
sys.path.insert(0, REPO)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--store-dir", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-size", type=int, default=50 * 1024 * 1024)
    ap.add_argument("--near-threshold", type=float, default=0.9)
    ap.add_argument("--near-max-docs", type=int, default=80000)
    ap.add_argument("--max-pairs", type=int, default=2_000_000)
    ap.add_argument("--related-samples", type=int, default=20)
    ap.add_argument("--skip-near", action="store_true")
    ap.add_argument("--include-members", action="store_true")
    ap.add_argument("--skip-exact", action="store_true")
    ap.add_argument("--max-sizes", type=int, default=200000)
    args = ap.parse_args(argv)

    os.environ["PIS_DB_PATH"] = args.db
    os.environ.setdefault("PIS_AI_MODE", "local")
    if args.store_dir:
        os.environ["PIS_EMBEDDING_STORE_DIR"] = args.store_dir
    os.environ.setdefault("PIS_EMBEDDING_MODEL", "bge-m3")

    from src.core.database import DatabaseManager
    from src.dedup import (
        DedupStore,
        ExactDuplicateEngine,
        NearDuplicateEngine,
        VersionTracker,
    )
    from src.dedup.rerank import rerank_search

    db = DatabaseManager(Path(args.db))
    store = DedupStore(db)
    report: dict = {"db": Path(args.db).name, "max_size": args.max_size}

    # -- exact --------------------------------------------------------------
    engine = ExactDuplicateEngine(db, store)
    if args.skip_exact:
        report["exact"] = {"skipped": True}
    sizes = engine.size_candidate_sizes(min_size=1, include_members=args.include_members, max_sizes=args.max_sizes)
    if not args.skip_exact:
        t0 = time.perf_counter()
        hash_stats = engine.hash_duplicate_candidates(min_size=1, max_size=args.max_size,
                                                       include_members=args.include_members,
                                                       max_sizes=args.max_sizes)
        first_wall = time.perf_counter() - t0
        summary = engine.summary(min_size=1, include_members=args.include_members)
        t1 = time.perf_counter()
        second = engine.hash_duplicate_candidates(min_size=1, max_size=args.max_size,
                                                  include_members=args.include_members,
                                                  max_sizes=args.max_sizes)
        second_wall = time.perf_counter() - t1
        report["exact"] = {
            "candidate_sizes": len(sizes),
            "hash_stats": {k: v for k, v in hash_stats.items() if k != "errors"},
            "first_pass_wall_s": round(first_wall, 2),
            "second_pass_wall_s": round(second_wall, 3),
            "second_pass_hashed": second["hashed"],
            "groups": summary["groups"], "duplicate_files": summary["duplicate_files"],
            "wasted_bytes": summary["wasted_bytes"], "largest_group": summary["largest_group"],
            "hash_coverage": summary["hash_stats"]["coverage"],
        }

    # -- near ---------------------------------------------------------------
    if not args.skip_near:
        from src.intelligence.embedding_store import EmbeddingMatrixStore
        estore = None
        if args.store_dir:
            estore = EmbeddingMatrixStore("bge-m3", "BAAI/bge-m3", 1024,
                                          base_dir=Path(args.store_dir))
            if not estore.load():
                estore = None
        near = NearDuplicateEngine(db, store, embed_store=estore)
        t0 = time.perf_counter()
        near_res = near.build(threshold=args.near_threshold, min_chars=200,
                              max_docs=args.near_max_docs, max_pairs=args.max_pairs)
        report["near"] = {**near_res, "wall_s": round(time.perf_counter() - t0, 2)}

    # -- versions -----------------------------------------------------------
    vt = VersionTracker(db, store)
    t0 = time.perf_counter()
    vres = vt.build()
    report["versions"] = {**vres, "wall_s": round(time.perf_counter() - t0, 2)}

    # -- related ------------------------------------------------------------
    if args.store_dir and not args.skip_near:
        from src.dedup.related import RelatedDocuments
        from src.intelligence.embedding_store import EmbeddingMatrixStore
        estore = EmbeddingMatrixStore("bge-m3", "BAAI/bge-m3", 1024, base_dir=Path(args.store_dir))
        if estore.load():
            rel = RelatedDocuments(db, dedup_store=store, embed_store=estore)
            ids = list(estore.meta.ids)[: args.related_samples]
            lat = []
            total = 0
            for fid in ids:
                t0 = time.perf_counter()
                res = rel.related(int(fid), limit=10)
                lat.append((time.perf_counter() - t0) * 1000)
                total += len(res)
            if lat:
                report["related"] = {"samples": len(lat), "avg_results": round(total / len(lat), 2),
                                     "p50_ms": round(statistics.median(lat), 2),
                                     "p95_ms": round(sorted(lat)[min(len(lat) - 1, int(0.95 * len(lat)))], 2)}

    # -- rerank -------------------------------------------------------------
    try:
        from src.intelligence.semantic_search import SemanticSearchEngine
        engine_sem = SemanticSearchEngine(db) if args.store_dir else None
    except Exception:
        engine_sem = None
    queries = ["contrat", "facture", "rapport", "project report", "vertrag"]
    lat = []
    for q in queries:
        t0 = time.perf_counter()
        rerank_search(db, engine_sem, q, limit=10, dedup_store=store)
        lat.append((time.perf_counter() - t0) * 1000)
    report["rerank"] = {"queries": len(queries), "p50_ms": round(statistics.median(lat), 2),
                        "max_ms": round(max(lat), 2)} if lat else {}

    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
