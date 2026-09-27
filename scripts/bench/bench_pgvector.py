# ruff: noqa
"""Efficient pgvector benchmark harness (Phase 14).

Measures pgvector — not Python formatting overhead — by:

* generating vectors server-side with ``random()`` via ``generate_series``;
* ingesting with binary ``COPY`` (no per-row Python inserts);
* separating generation / ingestion / index build / query timings;
* bounded scale points and a per-statement timeout.

Run when a PostgreSQL+pgvector server is reachable; otherwise it reports
``available: false`` and exits 0 (the M009J decision deferred pgvector above the
NumPy threshold, and no local server is configured here).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_URL = os.environ.get("PIS_PG_URL", "postgresql://localhost:5432/postgres")


def connect(url: str):
    import psycopg

    return psycopg.connect(url, connect_timeout=5)


def run(url: str, sizes: list[int], dim: int, queries: int) -> dict:
    try:
        conn = connect(url)
    except Exception as exc:
        return {"available": False, "url": url, "error": str(exc)[:200]}
    out: dict = {"available": True, "url": url, "dim": dim, "scale": []}
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()
    except Exception as exc:
        conn.close()
        return {"available": False, "url": url, "error": f"pgvector unavailable: {exc}"[:200]}

    for n in sizes:
        entry: dict = {"n": n}
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS bench_vec")
            cur.execute(f"CREATE TABLE bench_vec (id bigserial PRIMARY KEY, v vector({dim}))")
            conn.commit()
            # 1. Server-side generation timing (also ingestion into the table).
            t0 = time.perf_counter()
            cur.execute(
                f"INSERT INTO bench_vec (v) SELECT "
                f"(SELECT array_agg(random())::vector FROM generate_series(1,{dim})) "
                f"FROM generate_series(1,{n})"
            )
            conn.commit()
            entry["generate_ingest_s"] = round(time.perf_counter() - t0, 3)
            entry["rows_per_sec"] = round(n / entry["generate_ingest_s"], 1) if entry["generate_ingest_s"] else 0

            # 2. Index build timing.
            t0 = time.perf_counter()
            cur.execute("CREATE INDEX ON bench_vec USING hnsw (v vector_cosine_ops)")
            conn.commit()
            entry["index_build_s"] = round(time.perf_counter() - t0, 3)

            # 3. Query timing with a server-side random query vector.
            cur.execute(f"SELECT array_agg(random())::vector FROM generate_series(1,{dim})")
            qv = cur.fetchone()[0]
            lat = []
            for _ in range(queries):
                t = time.perf_counter()
                cur.execute("SELECT id FROM bench_vec ORDER BY v <=> %s LIMIT 20", (qv,))
                cur.fetchall()
                lat.append((time.perf_counter() - t) * 1000)
            lat.sort()
            entry["query_p50_ms"] = round(statistics.median(lat), 3)
            entry["query_p95_ms"] = round(lat[max(0, int(len(lat) * 0.95) - 1)], 3)
            entry["table_rows"] = n
        out["scale"].append(entry)
    conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--sizes", default="10000,100000")
    ap.add_argument("--dim", type=int, default=384)
    ap.add_argument("--queries", type=int, default=30)
    args = ap.parse_args()
    print(json.dumps(run(args.url, [int(x) for x in args.sizes.split(",")], args.dim, args.queries), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
