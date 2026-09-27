#!/usr/bin/env python3
"""M017 ingestion benchmark: email/legacy/EPUB/CHM/OCR coverage (aggregate only)."""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

REPO = "/home/chu/Projects/Personal_Intelligence_System_Suite"
sys.path.insert(0, REPO)

TARGET_EXTS = [".eml", ".msg", ".doc", ".xls", ".ppt", ".rtf", ".wpd", ".chm", ".epub"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-ext", type=int, default=100)
    ap.add_argument("--ocr-pdfs", type=int, default=20)
    args = ap.parse_args(argv)
    os.environ["PIS_DB_PATH"] = args.db
    os.environ.setdefault("PIS_AI_MODE", "local")

    from src.core.database import DatabaseManager
    from src.ingest.capabilities import capability_matrix
    from src.ingest.pipeline import IngestionPipeline

    db = DatabaseManager(Path(args.db))
    pipe = IngestionPipeline(db)
    db_before = Path(args.db).stat().st_size

    by_ext = {}
    overall = {}
    t0 = time.perf_counter()
    for ext in TARGET_EXTS:
        with db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, path, extension FROM files WHERE document_kind='PHYSICAL_FILE' "
                "AND extension=? AND COALESCE(state,'ACTIVE')='ACTIVE' "
                "AND (content_extracted=0 OR content_text IS NULL) LIMIT ?",
                (ext, int(args.per_ext))).fetchall()]
        counts = {}
        ext_t0 = time.perf_counter()
        for r in rows:
            outcome = pipe.extract_file(int(r["id"]), r["path"], extension=r["extension"])
            counts[outcome] = counts.get(outcome, 0) + 1
            overall[outcome] = overall.get(outcome, 0) + 1
        if rows:
            by_ext[ext] = {"tested": len(rows), "counts": counts,
                           "wall_s": round(time.perf_counter() - ext_t0, 2)}
    # image-only PDF OCR candidates (content already attempted, no text)
    ocr = {"tested": 0, "counts": {}}
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, path FROM files WHERE document_kind='PHYSICAL_FILE' AND extension='.pdf' "
            "AND content_extracted=1 AND content_text IS NULL AND COALESCE(state,'ACTIVE')='ACTIVE' LIMIT ?",
            (int(args.ocr_pdfs),)).fetchall()
    for r in rows:
        ocr["tested"] += 1
        outcome = pipe.extract_file(int(r["id"]), r["path"], extension=".pdf", ocr_explicit=True)
        ocr["counts"][outcome] = ocr["counts"].get(outcome, 0) + 1
    wall = time.perf_counter() - t0

    report = {
        "db": Path(args.db).name,
        "by_extension": by_ext,
        "overall_counts": overall,
        "ocr_pdf_candidates": ocr,
        "tested_total": sum(v["tested"] for v in by_ext.values()) + ocr["tested"],
        "wall_s": round(wall, 2),
        "docs_per_sec": round((sum(v["tested"] for v in by_ext.values()) + ocr["tested"]) / wall, 2) if wall else 0,
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "db_growth_bytes": Path(args.db).stat().st_size - db_before,
        "queue": pipe.queue.stats(),
        "capabilities": {f["format"]: f["status"] for f in capability_matrix()["formats"]},
    }
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
