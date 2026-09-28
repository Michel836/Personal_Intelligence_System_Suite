#!/usr/bin/env python3
"""Read-only / bounded real-life showcase for a populated PISS database.

Purpose: answer one question quickly on a real workstation: what can PISS use
*right now* from the current indexed disk, and which layers are ready for the
next activation step?

The script is intentionally non-destructive. It never scans, reconciles,
extracts, embeds, mutates lifecycle state, or sends content remotely.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from src.core.database import DatabaseManager, default_db_path


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _safe(callable_, default):
    try:
        return callable_()
    except Exception as exc:  # noqa: BLE001 - audit must continue
        return {"error": f"{type(exc).__name__}: {exc}", "fallback": default}


def build_report(db_path: Path, probes: list[str], limit: int) -> dict[str, Any]:
    db = DatabaseManager(db_path)
    report: dict[str, Any] = {
        "database": str(db_path),
        "read_only_showcase": True,
        "probes": probes,
    }

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        report["inventory"] = {
            "files_total": _scalar(conn, "SELECT COUNT(*) FROM files") or 0,
            "active": _scalar(conn, "SELECT COUNT(*) FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'") or 0,
            "missing": _scalar(conn, "SELECT COUNT(*) FROM files WHERE state='MISSING'") or 0,
            "content_extracted": _scalar(conn, "SELECT COUNT(*) FROM files WHERE COALESCE(content_extracted,0)=1") or 0,
            "with_content_text": _scalar(conn, "SELECT COUNT(*) FROM files WHERE content_text IS NOT NULL AND content_text!=''") or 0,
            "documents": _scalar(conn, "SELECT COUNT(*) FROM files WHERE file_type='document' AND COALESCE(state,'ACTIVE')='ACTIVE'") or 0,
            "emails": _scalar(conn, "SELECT COUNT(*) FROM files WHERE file_type='email' AND COALESCE(state,'ACTIVE')='ACTIVE'") or 0,
            "images": _scalar(conn, "SELECT COUNT(*) FROM files WHERE file_type='image' AND COALESCE(state,'ACTIVE')='ACTIVE'") or 0,
            "videos": _scalar(conn, "SELECT COUNT(*) FROM files WHERE file_type='video' AND COALESCE(state,'ACTIVE')='ACTIVE'") or 0,
            "archives": _scalar(conn, "SELECT COUNT(*) FROM files WHERE file_type='archive' AND COALESCE(state,'ACTIVE')='ACTIVE'") or 0,
        }
        report["scan_runs"] = _rows(
            conn,
            """SELECT id, root_path, status, files_seen, files_upserted, files_errors,
                      error_message, started_at, finished_at
                 FROM scan_runs ORDER BY id DESC LIMIT 10""",
        )
        report["states"] = _rows(
            conn,
            "SELECT COALESCE(state,'ACTIVE') AS state, COUNT(*) AS count FROM files GROUP BY COALESCE(state,'ACTIVE') ORDER BY count DESC",
        )
        report["extensions"] = _rows(
            conn,
            """SELECT extension, COUNT(*) AS count
                 FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'
                 GROUP BY extension ORDER BY count DESC LIMIT 20""",
        )
        report["largest_active"] = _rows(
            conn,
            """SELECT id, filename, path, size_bytes, file_type
                 FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'
                 ORDER BY size_bytes DESC LIMIT 10""",
        )

    stats = _safe(db.get_statistics, {})
    report["statistics_api"] = stats

    searches: dict[str, Any] = {}
    for probe in probes:
        lexical = _safe(lambda p=probe: db.search_files(p, limit=limit), [])
        searches[probe] = lexical
    report["lexical_search"] = searches

    # Dry-run extraction readiness: list eligible docs, never extract.
    def extraction_readiness():
        from src.ingest.pipeline import IngestionPipeline
        rows = IngestionPipeline(db).eligible(limit=limit)
        return {
            "eligible_count_sample": len(rows),
            "sample": [
                {"id": r.get("id"), "filename": r.get("filename"), "path": r.get("path"), "file_type": r.get("file_type")}
                for r in rows[: min(limit, 20)]
            ],
        }

    report["extraction_readiness"] = _safe(extraction_readiness, {})

    def dedup_status():
        from src.dedup import DedupStore
        store = DedupStore(db)
        return {
            "duplicates": store.duplicate_totals(),
            "near_duplicates": store.near_duplicate_stats(),
            "versions": store.version_family_stats(),
        }

    report["dedup"] = _safe(dedup_status, {})

    def semantic_status():
        from src.intelligence.semantic_search import SemanticSearchEngine
        engine = SemanticSearchEngine(db)
        available = bool(engine.is_available())
        out: dict[str, Any] = {"available": available}
        if available and probes:
            out["probe"] = probes[0]
            out["results"] = engine.search(probes[0], limit=min(limit, 10))
        return out

    report["semantic"] = _safe(semantic_status, {})

    def galaxy_status():
        from src.galaxy import GalaxyService
        service = GalaxyService(db)
        latest = service.store.latest_cluster_run()
        return {
            "latest_cluster_run": latest,
            "topics": service.store.topics(str(latest["run_id"]))[:10] if latest else [],
        }

    report["galaxy"] = _safe(galaxy_status, {})

    def dossier_status():
        from src.reports.dossiers import DossierService
        return DossierService(db).list_dossiers(limit=20)

    report["dossiers"] = _safe(dossier_status, [])

    return report


def print_human(report: dict[str, Any]) -> None:
    inv = report["inventory"]
    print("\n=== PISS 4TB REAL-LIFE SHOWCASE (READ-ONLY) ===")
    print(f"DB: {report['database']}")
    print(
        "Inventory: "
        f"total={inv['files_total']:,} active={inv['active']:,} missing={inv['missing']:,} "
        f"content={inv['with_content_text']:,}"
    )
    print(
        "Types: "
        f"documents={inv['documents']:,} emails={inv['emails']:,} images={inv['images']:,} "
        f"videos={inv['videos']:,} archives={inv['archives']:,}"
    )

    print("\nRecent scan runs:")
    for row in report.get("scan_runs", []):
        print(
            f"  #{row['id']} {row['status']} root={row['root_path']} "
            f"seen={row['files_seen']:,} upserted={row['files_upserted']:,} errors={row['files_errors']:,}"
        )

    print("\nLexical probes:")
    for probe, rows in report.get("lexical_search", {}).items():
        if isinstance(rows, dict) and "error" in rows:
            print(f"  {probe!r}: ERROR {rows['error']}")
            continue
        print(f"  {probe!r}: {len(rows)} result(s)")
        for row in rows[:10]:
            print(f"    [{row.get('id')}] {row.get('filename')}  state={row.get('state')}  {row.get('path')}")

    ext = report.get("extraction_readiness", {})
    print("\nExtraction readiness:", ext if isinstance(ext, dict) and "error" in ext else f"sample eligible={ext.get('eligible_count_sample', 0)}")

    sem = report.get("semantic", {})
    print("Semantic:", sem.get("error") if isinstance(sem, dict) and "error" in sem else f"available={sem.get('available')}")

    dedup = report.get("dedup", {})
    print("Dedup:", dedup.get("error") if isinstance(dedup, dict) and "error" in dedup else dedup)

    galaxy = report.get("galaxy", {})
    if isinstance(galaxy, dict) and "error" in galaxy:
        print("Galaxy:", galaxy["error"])
    else:
        print("Galaxy latest run:", galaxy.get("latest_cluster_run"))

    dossiers = report.get("dossiers", [])
    if isinstance(dossiers, dict) and "error" in dossiers:
        print("Dossiers:", dossiers["error"])
    else:
        print(f"Dossiers: {len(dossiers)}")

    print("\nNo files, lifecycle states, embeddings or content were modified by this showcase.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=default_db_path())
    parser.add_argument("--probe", action="append", default=[])
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--json-out", type=Path, default=Path("data/piss_4tb_showcase.json"))
    args = parser.parse_args()

    probes = args.probe or ["cv", "Michel", "facture", "contrat"]
    report = build_report(args.db, probes, max(1, min(args.limit, 100)))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print_human(report)
    print(f"\nFull JSON report: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
