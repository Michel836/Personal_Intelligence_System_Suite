# ruff: noqa
"""End-to-end synthetic pipeline benchmark: scan -> persist -> FTS -> extract
subset -> embed -> semantic search -> (optional) RAG.

Timings are reported per phase so the dominant cost is obvious.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import (  # noqa: E402
    ResourceSampler,
    generate_corpus,
    json_print,
    load_conditions,
    wipe,
)


def fresh_db(db_path: Path):
    from src.core.database import DatabaseManager

    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    return DatabaseManager(db_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10000")
    ap.add_argument("--corpus-root", default="/tmp/pis_bench/e2e_corpus")
    ap.add_argument("--db-dir", default="/tmp/pis_bench/db")
    ap.add_argument("--extract-subset", type=int, default=200)
    ap.add_argument("--embed-subset", type=int, default=200)
    ap.add_argument("--model", default="all-MiniLM-L6-v2")
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()
    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    report = {"conditions": load_conditions(), "runs": []}

    for n in [int(x) for x in args.sizes.split(",") if x.strip()]:
        corpus = Path(args.corpus_root) / str(n)
        if args.regen or not corpus.exists() or len(list(corpus.rglob("*"))) < n // 2:
            wipe(corpus)
            generate_corpus(corpus, n)
        db = fresh_db(db_dir / f"e2e_{n}.db")
        phases = {}

        from src.core.scan_service import ScanRequest, ScanService

        with ResourceSampler() as s:
            result = ScanService(db).run(ScanRequest(root=corpus, batch_size=2000))
        phases["scan_persist"] = {"wall_s": round(s.sample.wall, 3),
                                  "files": result.files_seen,
                                  "files_per_sec": round(result.files_seen / s.sample.wall, 1) if s.sample.wall else 0}

        with ResourceSampler() as s:
            hits = db.search_files(query="contrat", limit=50)
        phases["fts_search"] = {"wall_s": round(s.sample.wall, 4), "hits": len(hits)}

        # Extract a subset of text files and load content into the DB.
        subset = [r for r in db.search_files(limit=100000) if r["extension"] in (".txt", ".md", ".json", ".csv", ".html")]
        subset = subset[: args.extract_subset]
        with ResourceSampler() as s:
            from src.extractors.manager import ExtractionManager

            mgr = ExtractionManager(max_workers=4)
            for row in subset:
                p = Path(row["path"])
                if not p.exists():
                    continue
                r = mgr.extract_single(p)
                if r.success and r.content:
                    db.update_content(row["id"], r.content[:8000])
        phases["extract_subset"] = {"wall_s": round(s.sample.wall, 3),
                                    "docs": len(subset),
                                    "docs_per_sec": round(len(subset) / s.sample.wall, 1) if s.sample.wall else 0}

        docs = db.search_files(limit=100000)
        docs = [d for d in docs if d.get("content_text")][: args.embed_subset]
        from src.intelligence.embeddings import EmbeddingGenerator

        gen = EmbeddingGenerator(model_name=args.model)
        with ResourceSampler() as s:
            emb = gen.generate_batch_embeddings([d["content_text"] for d in docs], batch_size=64, show_progress=False)
        pairs = [(d["id"], e) for d, e in zip(docs, emb) if e is not None]
        phases["embed_subset"] = {"wall_s": round(s.sample.wall, 3), "docs": len(pairs),
                                  "embeddings_per_sec": round(len(pairs) / s.sample.wall, 1) if s.sample.wall else 0}

        if pairs:
            import numpy as np

            import src.intelligence.embedding_store as es

            base = Path("/tmp/pis_bench/e2e_store") / str(n)
            wipe(base)
            store = es.EmbeddingMatrixStore(f"e2e-{n}", args.model, gen.embedding_dim, base_dir=base)
            with ResourceSampler() as s:
                store.save([i for i, _ in pairs], np.vstack([e for _, e in pairs]))
            phases["store_save"] = {"wall_s": round(s.sample.wall, 3), "rows": len(pairs)}
            q = gen.generate_embedding("contrat de service confidentialite")
            with ResourceSampler() as s:
                ranked = store.search(q, top_k=20)
            phases["semantic_search"] = {"wall_s": round(s.sample.wall, 4), "hits": len(ranked)}

        phases["total_measured_s"] = round(sum(v.get("wall_s", 0) for v in phases.values()), 3)
        report["runs"].append({"n": n, "db_rows": db.get_statistics()["total_files"], "phases": phases})
        del gen
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass

    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
