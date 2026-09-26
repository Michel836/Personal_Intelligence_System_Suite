# ruff: noqa
"""Scanner benchmark: baseline throughput and bounded-concurrency sweep.

Modes
-----
scanonly : iterate FastScannerEngine.scan_paths only (no DB).
persist  : full canonical lifecycle (FastScannerEngine -> ScanService -> SQLite).
parallel : bounded stat-workers -> single DB writer prototype (see src/core/perf).

Each run uses a throwaway ``PIS_DB_PATH`` so the real index is never touched.
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
    median,
    wipe,
)


def _fresh_db(db_dir: Path, name: str) -> Path:
    db_dir.mkdir(parents=True, exist_ok=True)
    path = db_dir / name
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    return path


def run_persist(root: Path, db_path: Path, batch_size: int, limit=None):
    from src.core.database import DatabaseManager
    from src.core.scan_service import ScanRequest, ScanService

    db = DatabaseManager(db_path)
    service = ScanService(db)
    with ResourceSampler() as s:
        result = service.run(ScanRequest(root=root, limit=limit, batch_size=batch_size))
    stat = db.get_statistics()
    return {
        "status": result.status,
        "files_seen": result.files_seen,
        "files_upserted": result.files_upserted,
        "db_rows": stat["total_files"],
        "wall_s": round(s.sample.wall, 3),
        "files_per_sec": round(result.files_seen / s.sample.wall, 1) if s.sample.wall else 0,
        "cpu_pct": round(s.sample.cpu_pct, 1),
        "cpu_cores": s.cpu_cores,
        "rss_mb": round(s.sample.rss_mb, 1),
        "iowait_pct": getattr(s, "iowait_pct", 0.0),
        "disk_write_mb": round(s.sample.write_mb, 1),
    }


def run_scanonly(root: Path, limit=None):
    from src.scanner.fast_engine import FastScannerEngine

    scanner = FastScannerEngine()
    count = 0
    with ResourceSampler() as s:
        for _ in scanner.scan_paths([root], limit=limit):
            count += 1
    return {
        "files_seen": count,
        "wall_s": round(s.sample.wall, 3),
        "files_per_sec": round(count / s.sample.wall, 1) if s.sample.wall else 0,
        "cpu_pct": round(s.sample.cpu_pct, 1),
        "cpu_cores": s.cpu_cores,
        "rss_mb": round(s.sample.rss_mb, 1),
        "iowait_pct": getattr(s, "iowait_pct", 0.0),
    }


def run_parallel(root: Path, db_path: Path, workers: int, batch_size: int = 2000):
    """Scan with the optional producer/consumer overlap (PIS_SCAN_OVERLAP=1).

    Uses the canonical ScanService so a single DB writer is preserved; only the
    scan side runs in a bounded producer thread.
    """
    import os

    from src.core.database import DatabaseManager
    from src.core.perf_config import reset_resource_config
    from src.core.scan_service import ScanRequest, ScanService

    os.environ["PIS_SCAN_OVERLAP"] = "1"
    reset_resource_config()
    db = DatabaseManager(db_path)
    service = ScanService(db)
    with ResourceSampler() as s:
        result = service.run(ScanRequest(root=root, batch_size=batch_size))
    reset_resource_config()
    return {
        "workers": workers,
        "files_seen": result.files_seen,
        "db_rows": db.get_statistics()["total_files"],
        "wall_s": round(s.sample.wall, 3),
        "files_per_sec": round(result.files_seen / s.sample.wall, 1) if s.sample.wall else 0,
        "cpu_pct": round(s.sample.cpu_pct, 1),
        "cpu_cores": s.cpu_cores,
        "rss_mb": round(s.sample.rss_mb, 1),
        "iowait_pct": getattr(s, "iowait_pct", 0.0),
        "disk_write_mb": round(s.sample.write_mb, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--count", type=int, default=10000)
    ap.add_argument("--db-dir", default="/tmp/pis_bench/db")
    ap.add_argument("--mode", default="all", choices=["scanonly", "persist", "parallel", "all"])
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument("--workers", default="")
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if args.regen or not corpus.exists() or len(list(corpus.rglob("*"))) < args.count // 2:
        wipe(corpus)
        t = time.perf_counter()
        generate_corpus(corpus, args.count)
        print(f"# generated {args.count} files in {time.perf_counter() - t:.1f}s at {corpus}", file=sys.stderr)

    report = {"conditions": load_conditions(), "corpus": str(corpus), "count": args.count, "runs": {}}

    if args.mode in ("scanonly", "all"):
        runs = [run_scanonly(corpus) for _ in range(2)]
        report["runs"]["scanonly"] = runs

    if args.mode in ("persist", "all"):
        runs = []
        for i in range(2):
            db = _fresh_db(Path(args.db_dir), f"persist_{i}.db")
            runs.append(run_persist(corpus, db, args.batch_size))
        report["runs"]["persist"] = runs

    if args.mode in ("parallel", "all") and args.workers:
        worker_counts = [int(w) for w in args.workers.split(",") if w.strip()]
        runs = []
        for w in worker_counts:
            for i in range(2):
                db = _fresh_db(Path(args.db_dir), f"par_{w}_{i}.db")
                runs.append(run_parallel(corpus, db, w, args.batch_size))
        report["runs"]["parallel"] = runs

    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
