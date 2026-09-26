# ruff: noqa
"""EmbeddingMatrixStore incrementality benchmark (O(n) full rewrite vs append)."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import ResourceSampler, json_print, load_conditions, wipe  # noqa: E402


def make_matrix(n: int, dim: int) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.standard_normal((n, dim)).astype(np.float32)


def run(base: Path, initial: int, increments: list[int], dim: int = 1024) -> dict:
    import importlib

    import src.intelligence.embedding_store as es

    importlib.reload(es)
    store = es.EmbeddingMatrixStore("bench", "bench/model", dim, base_dir=base)
    next_id = 0
    matrix = make_matrix(initial, dim)
    with ResourceSampler() as s:
        store.save(list(range(next_id, next_id + initial)), matrix)
    save_stat = {"wall_s": round(s.sample.wall, 3), "rows_per_sec": round(initial / s.sample.wall, 1) if s.sample.wall else 0}
    next_id += initial

    incremental = []
    for inc in increments:
        inc_matrix = make_matrix(inc, dim)
        with ResourceSampler() as s:
            store.append(list(range(next_id, next_id + inc)), inc_matrix)
        next_id += inc
        incremental.append({
            "increment": inc,
            "total": next_id,
            "wall_s": round(s.sample.wall, 4),
            "rows_per_sec": round(inc / s.sample.wall, 1) if s.sample.wall else 0,
            "rss_mb": round(s.sample.rss_mb, 1),
        })
    disk = store._matrix_path.stat().st_size if store._matrix_path.exists() else 0
    return {"initial": initial, "save": save_stat, "increments": incremental,
            "final_count": store.meta.count if store.meta else 0, "disk_bytes": disk}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/tmp/pis_bench/embstore")
    ap.add_argument("--initial", default="10000,100000,1000000")
    ap.add_argument("--increments", default="100,1000,10000")
    args = ap.parse_args()
    base = Path(args.base)
    wipe(base)
    report = {"conditions": load_conditions(), "runs": []}
    for n in [int(x) for x in args.initial.split(",") if x.strip()]:
        report["runs"].append(run(base / str(n), n, [int(x) for x in args.increments.split(",")]))
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
