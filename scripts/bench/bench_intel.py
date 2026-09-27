#!/usr/bin/env python3
"""M015 document-intelligence benchmark (aggregate only; no private text).

Runs the local language/entity/category/PII pipeline over a DB copy and reports
aggregate distributions, throughput, DB growth, incremental no-change cost and
filtered-search latency.
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
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-chars", type=int, default=50)
    ap.add_argument("--include-members", action="store_true")
    ap.add_argument("--store-dir", default="")
    args = ap.parse_args(argv)

    os.environ["PIS_DB_PATH"] = args.db
    os.environ.setdefault("PIS_AI_MODE", "local")
    if args.store_dir:
        os.environ["PIS_EMBEDDING_STORE_DIR"] = args.store_dir

    from src.core.database import DatabaseManager
    from src.intel import IntelPipeline, IntelStore, filter_options

    db = DatabaseManager(Path(args.db))
    store = IntelStore(db)
    embed_store = None
    if args.store_dir:
        try:
            from src.intelligence.embedding_store import EmbeddingMatrixStore
            embed_store = EmbeddingMatrixStore("bge-m3", "BAAI/bge-m3", 1024, base_dir=Path(args.store_dir))
            if not embed_store.load():
                embed_store = None
        except Exception:
            embed_store = None
    pipe = IntelPipeline(db, store=store, embed_store=embed_store)

    db_before = Path(args.db).stat().st_size
    candidates = {int(d["id"]) for d in store.stale_documents(
        limit=(args.limit or None), min_chars=args.min_chars, include_members=args.include_members)}
    t0 = time.perf_counter()
    run1 = pipe.run(limit=(args.limit or None), min_chars=args.min_chars,
                    include_members=args.include_members)
    wall1 = time.perf_counter() - t0
    db_after = Path(args.db).stat().st_size

    # No-change check: the just-processed documents must no longer be stale.
    t0 = time.perf_counter()
    still_stale = {int(d["id"]) for d in store.stale_documents(
        limit=(args.limit or None), min_chars=args.min_chars, include_members=args.include_members)}
    wall2 = time.perf_counter() - t0
    run2 = {"processed": len(candidates & still_stale)}

    # filtered search latency
    opts = filter_options(store)
    lat = []
    for _ in range(5):
        t0 = time.perf_counter()
        db.search_files(query="", language="fr", limit=20)
        lat.append((time.perf_counter() - t0) * 1000)
    for _ in range(5):
        t0 = time.perf_counter()
        db.search_files(query="", has_pii=True, limit=20)
        lat.append((time.perf_counter() - t0) * 1000)

    report = {
        "db": Path(args.db).name,
        "first_pass": run1,
        "first_pass_wall_s": round(wall1, 2),
        "second_pass_processed": run2["processed"],
        "second_pass_wall_s": round(wall2, 3),
        "db_growth_bytes": db_after - db_before,
        "stats": store.stats(),
        "distinct_languages": len(opts["languages"]),
        "distinct_categories": len(opts["categories"]),
        "distinct_entity_types": len(opts["entity_types"]),
        "filtered_search_p50_ms": round(statistics.median(lat), 3) if lat else None,
    }
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
