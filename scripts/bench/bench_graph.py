#!/usr/bin/env python3
"""M016 timeline / relationship-graph / priority benchmark (aggregate only)."""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

REPO = "/home/chu/Projects/Personal_Intelligence_System_Suite"
sys.path.insert(0, REPO)


def _pct(vals, p):
    if not vals:
        return None
    vs = sorted(vals)
    return round(vs[min(len(vs) - 1, int(round(p / 100 * (len(vs) - 1))))], 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=30)
    args = ap.parse_args(argv)
    os.environ["PIS_DB_PATH"] = args.db

    from src.core.database import DatabaseManager
    from src.graph import DocumentGraph, to_networkx

    db = DatabaseManager(Path(args.db))
    db_before = Path(args.db).stat().st_size
    g = DocumentGraph(db)

    # timeline range queries
    tl = []
    for _ in range(5):
        t0 = time.perf_counter()
        g.timeline_events(group="month")
        tl.append((time.perf_counter() - t0) * 1000)

    # pick sample document ids that participate in relations
    with db.get_connection() as conn:
        ids = [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT file_id FROM doc_entities LIMIT 500").fetchall()]
        if not ids:
            ids = [int(r[0]) for r in conn.execute(
                "SELECT id FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE' LIMIT 500").fetchall()]
    rng = random.Random(7)
    sample = rng.sample(ids, min(args.samples, len(ids)))

    hop1, hop2, prio = [], [], []
    node_counts = []
    for fid in sample:
        t0 = time.perf_counter()
        nb1 = g.neighborhood(fid, depth=1)
        hop1.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        g.neighborhood(fid, depth=2)
        hop2.append((time.perf_counter() - t0) * 1000)
        node_counts.append((len(nb1["nodes"]), len(nb1["edges"])))
        t0 = time.perf_counter()
        g.priority(fid)
        prio.append((time.perf_counter() - t0) * 1000)

    # entity graph
    t0 = time.perf_counter()
    eg = g.entity_graph(min_docs=2, max_entities=200, max_edges=1000)
    eg_ms = (time.perf_counter() - t0) * 1000

    # graph rendering (layout) at increasing sizes
    render = {}
    base = to_networkx(g.neighborhood(sample[0], depth=2, max_nodes=500, max_edges=1500)) if sample else None
    if base is not None:
        import networkx as nx
        for n in (50, 100, 500):
            nodes = list(base.nodes())[:n]
            sub = base.subgraph(nodes).copy()
            t0 = time.perf_counter()
            if sub.number_of_nodes() > 0:
                nx.spring_layout(sub, k=0.6, iterations=30, seed=7)
            render[str(n)] = round((time.perf_counter() - t0) * 1000, 2)

    report = {
        "db": Path(args.db).name,
        "timeline_p50_ms": _pct(tl, 50), "timeline_p95_ms": _pct(tl, 95),
        "hop1_p50_ms": _pct(hop1, 50), "hop1_p95_ms": _pct(hop1, 95),
        "hop2_p50_ms": _pct(hop2, 50), "hop2_p95_ms": _pct(hop2, 95),
        "priority_p50_ms": _pct(prio, 50),
        "entity_graph_ms": round(eg_ms, 2),
        "entity_graph_stats": eg["stats"],
        "render_layout_ms": render,
        "avg_hop1_nodes": round(statistics.mean([n for n, _ in node_counts]), 2) if node_counts else 0,
        "avg_hop1_edges": round(statistics.mean([e for _, e in node_counts]), 2) if node_counts else 0,
        "relation_stats": g.relations.stats(),
        "samples": len(sample),
        "db_growth_bytes": Path(args.db).stat().st_size - db_before,
    }
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
