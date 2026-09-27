#!/usr/bin/env python3
"""M019 maintenance / backup / restore benchmark (aggregate only).

Copies a trial database to a scratch location (SQLite backup API), then measures
integrity, analyze/optimize, FTS/semantic consistency, a full backup and a
restore-to-staging. Never touches the production DB or the source corpus; the
report contains counts, checksums, durations and sizes only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _counts(db) -> dict:
    out = {}
    with db.get_connection() as conn:
        for table in ("files", "content_hashes", "version_families", "semantic_state",
                      "extraction_queue", "email_threads"):
            try:
                out[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except Exception:  # noqa: BLE001
                out[table] = None
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-db", required=True)
    ap.add_argument("--work-dir", default="/home/chu/.pis-trials/m019")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-integrity", action="store_true")
    args = ap.parse_args(argv)

    import os
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    os.environ["PIS_BACKUP_DIR"] = str(work / "backups")
    os.environ["PIS_EMBEDDING_STORE_DIR"] = str(work / "embeddings")

    from src.core.database import DatabaseManager
    from src.ops.backup import create_backup, restore_backup, verify_backup
    from src.ops.maintenance import MaintenanceService
    from src.ops.pgvector import benchmark as pg_benchmark
    from src.ops.pgvector import decide

    report: dict = {"source_db": Path(args.source_db).name, "steps": {}}
    scratch = work / "files.db"
    t0 = time.perf_counter()
    _copy_sqlite(Path(args.source_db), scratch)
    report["steps"]["copy"] = {"wall_s": round(time.perf_counter() - t0, 3),
                               "bytes": scratch.stat().st_size}

    db = DatabaseManager(scratch)
    report["counts_before"] = _counts(db)
    svc = MaintenanceService(db)

    if not args.skip_integrity:
        report["steps"]["integrity"] = svc.integrity_check()
    report["steps"]["analyze"] = svc.analyze()
    report["steps"]["optimize"] = svc.optimize()
    report["steps"]["fts_consistency"] = svc.fts_consistency()
    report["steps"]["semantic_consistency"] = svc.semantic_consistency()
    report["steps"]["orphan_scan"] = svc.orphan_scan()

    backup = create_backup(db)
    report["steps"]["backup"] = {"backup_id": backup.backup_id, "wall_s": backup.duration_s,
                                 "archive_bytes": Path(backup.archive_path).stat().st_size,
                                 "archive_sha256": _sha256(Path(backup.archive_path)),
                                 "components": len(backup.manifest["components"]["semantic"])}
    report["steps"]["verify"] = {k: v for k, v in verify_backup(backup.archive_path).items()
                                 if k != "manifest"}

    target = work / "restored" / "files.db"
    if target.exists():
        target.unlink()
    restore = restore_backup(backup.archive_path, target_db=target, confirm=True)
    report["steps"]["restore"] = restore.as_dict()
    if target.exists():
        report["restored_sha256"] = _sha256(target)
        restored_db = DatabaseManager(target)
        report["counts_after"] = _counts(restored_db)
        report["counts_match"] = report["counts_before"] == report["counts_after"]

    pg = pg_benchmark(sizes=[10_000], dim=1024, queries=5)
    report["pgvector"] = {"benchmark": pg, "decision": decide(benchmark_result=pg)}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
