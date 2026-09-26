# ruff: noqa
"""FTS5 throughput benchmark: indexing overhead and query latency."""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import ResourceSampler, json_print, load_conditions  # noqa: E402

WORDS = ("contrat service confidentialite paiement facture credit pret "
         "hypotheque notaire avocat tribunal accord clause document rapport "
         "analyse projet budget client fournisseur livraison").split()


def make_rows(n: int):
    from src.scanner.models import FileInfo, FileType, Priority

    now = datetime(2024, 1, 1, 12, 0, 0)
    infos = []
    contents = []
    for i in range(n):
        p = Path(f"/tmp/pis_bench/fts/{i:08d}.txt")
        infos.append(FileInfo(path=p, filename=f"contrat_{i}.txt", size_bytes=256,
                              created_at=now, modified_at=now, extension=".txt",
                              file_type=FileType.DOCUMENT, priority=Priority.MEDIUM))
        body = " ".join(WORDS[(i + j) % len(WORDS)] for j in range(60))
        contents.append(f"{body} reference{i}")
    return infos, contents


def build(db_path: Path, n: int, with_triggers: bool = True):
    from src.core.database import DatabaseManager

    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    db = DatabaseManager(db_path)
    infos, contents = make_rows(n)
    if not with_triggers:
        with db.get_connection() as conn:
            for t in ("files_fts_insert", "files_fts_delete", "files_fts_update"):
                conn.execute(f"DROP TRIGGER IF EXISTS {t}")
            conn.commit()
    with ResourceSampler() as s:
        db.save_files_batch(infos, batch_size=5000)
        with db.get_connection() as conn:
            conn.executemany(
                "UPDATE files SET content_text = ?, content_extracted = 1 WHERE id = ?",
                [(c, i + 1) for i, c in enumerate(contents)],
            )
            conn.commit()
    sizes = {
        "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "wal_bytes": Path(str(db_path) + "-wal").stat().st_size if Path(str(db_path) + "-wal").exists() else 0,
    }
    with db.get_connection() as conn:
        fts_rows = conn.execute("SELECT count(*) FROM files_fts").fetchone()[0]
    return {
        "n": n,
        "with_triggers": with_triggers,
        "index_wall_s": round(s.sample.wall, 3),
        "rows_per_sec": round(n / s.sample.wall, 1) if s.sample.wall else 0,
        "cpu_pct": round(s.sample.cpu_pct, 1),
        "rss_mb": round(s.sample.rss_mb, 1),
        "fts_rows": fts_rows,
        **sizes,
    }


def queries(db_path: Path):
    from src.core.database import DatabaseManager

    db = DatabaseManager(db_path)
    cases = {
        "phrase": '"contrat service"',
        "prefix": "confid*",
        "multi_term": "contrat facture client",
        "single": "contrat",
        "filtered": "contrat",
    }
    out = {}
    for name, q in cases.items():
        lat = []
        for _ in range(30):
            t = time.perf_counter()
            if name == "filtered":
                db.search_files(query=q, file_type=None, extension=".txt", limit=50)
            else:
                db.search_files(query=q, limit=50)
            lat.append((time.perf_counter() - t) * 1000)
        lat.sort()
        out[name] = {
            "p50_ms": round(statistics.median(lat), 3),
            "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 3),
            "max_ms": round(lat[-1], 3),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10000,100000")
    ap.add_argument("--db-dir", default="/tmp/pis_bench/db")
    ap.add_argument("--no-trigger-probe", action="store_true")
    args = ap.parse_args()
    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    report = {"conditions": load_conditions(), "index": [], "queries": {}}
    last_db = None
    for n in [int(x) for x in args.sizes.split(",") if x.strip()]:
        db = db_dir / f"fts_{n}.db"
        report["index"].append(build(db, n, with_triggers=True))
        if not args.no_trigger_probe:
            report["index"].append({
                "note": "no-trigger probe (documents trigger overhead)",
                **build(db_dir / f"fts_{n}_notrig.db", n, with_triggers=False),
            })
        last_db = db
    if last_db is not None:
        report["queries"] = queries(last_db)
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
