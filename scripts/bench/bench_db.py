# ruff: noqa
"""SQLite write-path benchmark: batch sizes, single-row, PRAGMA audit.

Measures DatabaseManager.save_files_batch + save_file against fresh temp DBs so
the real index is untouched.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import ResourceSampler, json_print, load_conditions, median  # noqa: E402


def make_infos(n: int, prefix: str = "b"):
    from src.scanner.models import FileInfo, FileType, Priority

    now = datetime(2024, 1, 1, 12, 0, 0)
    out = []
    for i in range(n):
        p = Path(f"/tmp/pis_bench/mem/{prefix}/{i:08d}.txt")
        out.append(FileInfo(
            path=p, filename=p.name, size_bytes=128, created_at=now, modified_at=now,
            extension=".txt", file_type=FileType.DOCUMENT, priority=Priority.MEDIUM,
            device_id=1, inode=1000 + i,
        ))
    return out


def db_sizes(db_path: Path) -> dict:
    def size(p):
        return p.stat().st_size if p.exists() else 0
    return {
        "db_bytes": size(db_path),
        "wal_bytes": size(Path(str(db_path) + "-wal")),
        "shm_bytes": size(Path(str(db_path) + "-shm")),
    }


def pragma_snapshot(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        names = ["journal_mode", "synchronous", "cache_size", "temp_store",
                 "mmap_size", "wal_autocheckpoint", "busy_timeout", "foreign_keys"]
        return {n: conn.execute(f"PRAGMA {n}").fetchone()[0] for n in names}
    finally:
        conn.close()


def bench_batch(db_path: Path, infos, batch_size: int, *, single: bool = False) -> dict:
    from src.core.database import DatabaseManager

    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    db = DatabaseManager(db_path)
    with ResourceSampler() as s:
        if single:
            for info in infos:
                db.save_file(info)
        else:
            db.save_files_batch(infos, batch_size=batch_size)
    n = len(infos)
    return {
        "batch_size": 1 if single else batch_size,
        "mode": "single" if single else "batch",
        "rows": n,
        "wall_s": round(s.sample.wall, 3),
        "rows_per_sec": round(n / s.sample.wall, 1) if s.sample.wall else 0,
        "cpu_pct": round(s.sample.cpu_pct, 1),
        "rss_mb": round(s.sample.rss_mb, 1),
        "disk_write_mb": round(s.sample.write_mb, 1),
        **db_sizes(db_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10000)
    ap.add_argument("--db-dir", default="/tmp/pis_bench/db")
    ap.add_argument("--single", action="store_true")
    args = ap.parse_args()

    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    infos = make_infos(args.rows)
    report = {"conditions": load_conditions(), "rows": args.rows, "results": []}
    report["pragmas_default"] = pragma_snapshot(db_dir / "pragma_probe.db") if (db_dir / "pragma_probe.db").exists() else {}

    if args.single:
        report["results"].append(bench_batch(db_dir / "single.db", infos, 1, single=True))

    for bs in (100, 500, 1000, 2000, 5000, 10000):
        runs = [bench_batch(db_dir / f"batch_{bs}_{i}.db", infos, bs) for i in range(2)]
        report["results"].append({
            "batch_size": bs,
            "wall_s": round(median([r["wall_s"] for r in runs]), 3),
            "rows_per_sec": round(median([r["rows_per_sec"] for r in runs]), 1),
            "cpu_pct": runs[-1]["cpu_pct"],
            "rss_mb": runs[-1]["rss_mb"],
            "db_bytes": runs[-1]["db_bytes"],
            "wal_bytes": runs[-1]["wal_bytes"],
            "disk_write_mb": runs[-1]["disk_write_mb"],
        })

    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
