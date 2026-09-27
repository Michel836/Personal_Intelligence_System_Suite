# ruff: noqa
"""BLAS threading benchmark for the semantic matrix fast path.

OpenBLAS/MKL thread count is fixed at import, so each measurement runs in a
fresh child process with the thread env var set before numpy import.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def child(n: int, dim: int, reps: int) -> int:
    import numpy as np

    rng = np.random.default_rng(0)
    matrix = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix /= norms
    q = rng.standard_normal(dim).astype(np.float32)
    q /= np.linalg.norm(q)
    lat = []
    for _ in range(reps):
        t = time.perf_counter()
        scores = matrix @ q
        order = np.lexsort((np.arange(n), -scores))[:20]
        _ = [int(order[0]), float(scores[order[0]])]
        lat.append((time.perf_counter() - t) * 1000)
    print(json.dumps({
        "n": n, "dim": dim,
        "p50_ms": round(statistics.median(lat), 4),
        "p95_ms": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 4),
        "min_ms": round(min(lat), 4),
        "threads": int(os.environ.get("OPENBLAS_NUM_THREADS", "0")),
    }))
    return 0


def run_parent(n_list, dim, threads_list, reps):
    report = {"dim": dim, "reps": reps, "results": []}
    for n in n_list:
        for t in threads_list:
            env = dict(os.environ)
            env["OPENBLAS_NUM_THREADS"] = str(t)
            env["OMP_NUM_THREADS"] = str(t)
            env["MKL_NUM_THREADS"] = str(t)
            env["OPENBLAS_MAIN_FREE"] = "1"
            proc = subprocess.run(
                [sys.executable, __file__, "--child", "--n", str(n),
                 "--dim", str(dim), "--reps", str(reps)],
                env=env, capture_output=True, text=True, cwd=str(ROOT),
            )
            line = (proc.stdout.strip().splitlines() or ["{}"])[-1]
            try:
                res = json.loads(line)
            except Exception:
                res = {"error": proc.stderr[-400:]}
            res["requested_threads"] = t
            report["results"].append(res)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--n", type=int, default=100000)
    ap.add_argument("--dim", type=int, default=384)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--ns", default="10000,100000")
    ap.add_argument("--threads", default="1,2,4,8,16,32")
    args = ap.parse_args()
    if args.child:
        raise SystemExit(child(args.n, args.dim, args.reps))
    raise SystemExit(run_parent(
        [int(x) for x in args.ns.split(",")],
        args.dim,
        [int(x) for x in args.threads.split(",")],
        args.reps,
    ))
