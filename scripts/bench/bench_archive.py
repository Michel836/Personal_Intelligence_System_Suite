# ruff: noqa
"""Archive pipeline benchmark: member indexing/extraction and concurrency."""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import (  # noqa: E402
    ResourceSampler,
    generate_corpus,
    json_print,
    load_conditions,
    make_archive,
    wipe,
)


def build_archives(root: Path, count: int, members: int) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    payload = b"contrat service confidentialite " * 8
    made = []
    for i in range(count):
        p = root / f"archive_{i:03d}.zip"
        make_archive(p, members=members, payload=payload)
        made.append(p)
    return made


def index_one(db_path: Path, archive: Path) -> dict:
    import os

    os.environ["PIS_DB_PATH"] = str(db_path)

    from src.core.database import DatabaseManager
    from src.archives.indexer import ArchiveIndexer

    db = DatabaseManager(db_path)
    # Register the archive as a physical row first.
    from datetime import datetime

    from src.scanner.models import FileInfo, FileType, Priority

    info = FileInfo(
        path=archive, filename=archive.name, size_bytes=archive.stat().st_size,
        created_at=datetime.now(), modified_at=datetime.now(), extension=".zip",
        file_type=FileType.ARCHIVE, priority=Priority.HIGH,
    )
    parent_id = db.save_file(info)
    indexer = ArchiveIndexer(db)
    t = time.perf_counter()
    result = indexer.index_archive(parent_id, str(archive), force=True)
    return {
        "archive": archive.name,
        "members": result.member_count,
        "extracted": result.extracted,
        "failed": result.failed,
        "status": result.status,
        "wall_s": round(time.perf_counter() - t, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/pis_bench/archives")
    ap.add_argument("--members", default="100,1000,10000")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--workers", default="1,2,4")
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()
    root = Path(args.dir)
    report = {"conditions": load_conditions(), "results": []}
    db_dir = Path("/tmp/pis_bench/db")
    db_dir.mkdir(parents=True, exist_ok=True)

    for members in [int(x) for x in args.members.split(",") if x.strip()]:
        if args.regen or not (root / f"archive_000.zip").exists():
            wipe(root)
            build_archives(root, args.count, members)
        archives = sorted(root.glob("*.zip"))
        # single-archive timing (largest members) then concurrency on all.
        from scripts.bench.common import ResourceSampler as RS  # local alias

        single_db = db_dir / f"arc_single_{members}.db"
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(single_db) + suffix)
            if p.exists():
                p.unlink()
        with RS() as s:
            one = index_one(single_db, archives[0])
        report["results"].append({
            "phase": "single", "members_per_archive": members,
            "members": one["members"], "extracted": one["extracted"],
            "wall_s": one["wall_s"],
            "members_per_sec": round(one["members"] / one["wall_s"], 1) if one["wall_s"] else 0,
            "cpu_pct": round(s.sample.cpu_pct, 1),
        })
        for workers in [int(x) for x in args.workers.split(",") if x.strip()]:
            db = db_dir / f"arc_{members}_{workers}.db"
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(db) + suffix)
                if p.exists():
                    p.unlink()
            with RS() as s:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = [ex.submit(index_one, db, a) for a in archives]
                    done = [f.result() for f in as_completed(futs)]
            total_members = sum(d["members"] for d in done)
            report["results"].append({
                "phase": "concurrent", "members_per_archive": members,
                "workers": workers, "archives": len(archives), "members": total_members,
                "wall_s": round(s.sample.wall, 3),
                "members_per_sec": round(total_members / s.sample.wall, 1) if s.sample.wall else 0,
                "cpu_pct": round(s.sample.cpu_pct, 1),
                "rss_mb": round(s.sample.rss_mb, 1),
            })
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
