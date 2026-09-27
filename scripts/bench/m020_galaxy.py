#!/usr/bin/env python3
"""M020 real-corpus galaxy / clustering / topic benchmark (aggregate only).

Works on a *copy* of a trial database and a read-only embedding store. It never
touches the source corpus or the production DB. Reports runtimes, peak RSS,
payload sizes and derived-table sizes only — no document text, filenames or
private paths are written to the report.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _copy_sqlite(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(str(src))
    try:
        d = sqlite3.connect(str(dest))
        try:
            with d:
                s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def _rss_mb() -> float:
    try:
        import psutil
        return float(psutil.Process().memory_info().rss) / 1e6
    except Exception:  # noqa: BLE001
        return 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-db", required=True)
    ap.add_argument("--store-dir", required=True)
    ap.add_argument("--store-key", default="bge-m3")
    ap.add_argument("--store-name", default="BAAI/bge-m3")
    ap.add_argument("--store-dim", type=int, default=1024)
    ap.add_argument("--work-dir", default="/home/chu/.pis-trials/m020")
    ap.add_argument("--stages", default="5000,20000,full")
    ap.add_argument("--k", type=int, default=16)
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--max-rss-gb", type=float, default=8.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    scratch = work / "files.db"

    report: dict[str, Any] = {"source_db": Path(args.source_db).name, "stages": {}}
    t0 = time.perf_counter()
    _copy_sqlite(Path(args.source_db), scratch)
    report["copy_s"] = round(time.perf_counter() - t0, 3)
    report["db_bytes"] = scratch.stat().st_size

    from src.core.database import DatabaseManager
    from src.galaxy import GalaxyService, GalaxyStore, scale_tier
    from src.intelligence.embedding_store import EmbeddingMatrixStore

    db = DatabaseManager(scratch)
    store = EmbeddingMatrixStore(args.store_key, args.store_name, args.store_dim,
                                 base_dir=Path(args.store_dir))
    if not store.load() or store.meta is None or store.matrix is None:
        report["error"] = "embedding store unavailable"
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))  # noqa: T201
        return 2
    all_ids = [int(i) for i in store.meta.ids]
    report["store_count"] = len(all_ids)

    def _stage_size(stage: str) -> int:
        return len(all_ids) if stage == "full" else min(int(stage), len(all_ids))

    for stage in args.stages.split(","):
        size = _stage_size(stage.strip())
        subset = all_ids[:size]
        entry: dict[str, Any] = {"input": size, "tier": scale_tier(size)}
        svc = GalaxyService(db, embedding_store=store, store=GalaxyStore(db))
        svc.store_stats()
        rss_before = _rss_mb()

        t0 = time.perf_counter()
        galaxy = svc.galaxy(scope={"kind": "file_ids", "ids": subset}, method="pca",
                            limit=min(size, args.limit), color_by="cluster", k=args.k,
                            with_topics=False, persist=False)
        entry["projection_s"] = round(time.perf_counter() - t0, 3)
        entry["projection"] = galaxy.get("projection", {})
        entry["point_count"] = len(galaxy.get("points", []))
        entry["projection_payload_bytes"] = len(json.dumps(galaxy.get("points", [])))
        entry["rss_after_projection_mb"] = round(_rss_mb(), 1)

        t0 = time.perf_counter()
        built = svc.build_clusters(scope={"kind": "file_ids", "ids": subset}, k=args.k,
                                   persist=True)
        entry["clustering_s"] = round(time.perf_counter() - t0, 3)
        entry["clustering"] = built["result"].as_dict()
        entry["rss_after_clustering_mb"] = round(_rss_mb(), 1)

        t0 = time.perf_counter()
        topics = svc.build_topics(built["run_id"], max_docs_per_cluster=40,
                                  max_representatives=5)
        entry["topics_s"] = round(time.perf_counter() - t0, 3)
        entry["topic_count"] = len(topics)
        entry["representatives"] = sum(len(t.representatives) for t in topics)
        entry["rss_after_topics_mb"] = round(_rss_mb(), 1)

        # Representative UI payload bytes for the cluster/topic panel.
        entry["topic_payload_bytes"] = len(json.dumps([t.as_dict() for t in topics]))

        t0 = time.perf_counter()
        graph = svc.cluster_graph(built["run_id"])
        entry["graph_s"] = round(time.perf_counter() - t0, 3)
        entry["graph_nodes"] = len(graph["nodes"])
        entry["graph_edges"] = len(graph["edges"])

        t0 = time.perf_counter()
        series = svc.topic_over_time(built["run_id"], group="month")
        entry["topic_time_s"] = round(time.perf_counter() - t0, 3)
        entry["topic_time_points"] = len(series["series"])

        entry["derived"] = svc.store.stats()
        entry["peak_rss_mb"] = round(max(rss_before, _rss_mb()), 1)
        entry["status"] = svc.store.run_status(
            svc.store.cluster_run(built["run_id"]) or {},
            current_freshness=svc.current_freshness())["status"]
        report["stages"][stage.strip()] = entry
        if _rss_mb() / 1000.0 > args.max_rss_gb:
            report["stopped_early"] = f"RSS > {args.max_rss_gb} GB at stage {stage}"
            break

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
