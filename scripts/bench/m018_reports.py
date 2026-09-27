#!/usr/bin/env python3
"""M018 report/dossier/export benchmark (aggregate only).

Builds representative reports from an existing trial DB (M013-M017 data) and
measures assembly, HTML and PDF time, memory, output size and warnings. The
report JSON contains only counts, timings and sizes — never a filename, path or
document excerpt. Generated artifacts live under the trial directory, never in
the repository.

Report types whose supporting tables are absent from the chosen DB are skipped
and recorded as such.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _first_thread(db) -> int | None:
    try:
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT file_id FROM email_threads t WHERE ("
                "SELECT COUNT(*) FROM email_threads x WHERE x.thread_key=t.thread_key) > 1 "
                "LIMIT 1").fetchone()
        return int(row[0]) if row else None
    except Exception:  # noqa: BLE001
        return None


def _tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--out-dir", default="/home/chu/.pis-trials/m018/exports")
    ap.add_argument("--search-limit", type=int, default=50)
    ap.add_argument("--dossier-limit", type=int, default=100)
    ap.add_argument("--skip-pdf", action="store_true")
    args = ap.parse_args(argv)

    os.environ["PIS_EXPORT_DIR"] = args.out_dir
    os.environ.setdefault("PIS_AI_MODE", "local")

    from src.core.database import DatabaseManager
    from src.reports import (
        DossierService,
        ExportService,
        PrivacyMode,
        ReportKind,
        ReportStore,
    )
    from src.reports.reconstruction import (
        reconstruct_email_thread,
        reconstruct_versions,
    )

    db = DatabaseManager(Path(args.db))
    store = ReportStore(db)
    svc = ExportService(db, store=store, out_dir=Path(args.out_dir))
    report: dict[str, object] = {"db": Path(args.db).name, "reports": {}, "skipped": {}}
    t_all = time.perf_counter()

    def build(key: str, definition, *, formats=("HTML", "JSON"), timed_pdf: bool = False) -> None:
        try:
            t0 = time.perf_counter()
            ir = svc.builder.build(definition)
            assembly = time.perf_counter() - t0
            from src.reports.html_export import render_html
            t1 = time.perf_counter()
            html = render_html(ir)
            html_s = time.perf_counter() - t1
            pdf_s = 0.0
            pdf_bytes = 0
            used_formats = formats
            if timed_pdf:
                t2 = time.perf_counter()
                result = svc._write_pdf(definition, html, ir.logical_fingerprint())
                pdf_s = time.perf_counter() - t2
                if result[0] is not None:
                    pdf_bytes = result[0].size_bytes
                else:
                    used_formats = tuple(f for f in formats if f != "PDF")
                    report.setdefault("warnings", []).append(  # type: ignore[union-attr]
                        f"{key}: pdf unavailable")
            report["reports"][key] = {
                "sections": len(ir.sections), "sources": len(ir.sources),
                "warnings": len(ir.warnings), "assembly_s": round(assembly, 3),
                "html_s": round(html_s, 3), "html_bytes": len(html.encode("utf-8")),
                "pdf_s": round(pdf_s, 3) if timed_pdf else None,
                "pdf_bytes": pdf_bytes if timed_pdf else None,
                "formats": list(used_formats),
            }
        except Exception as exc:  # noqa: BLE001
            report["skipped"][key] = type(exc).__name__

    # A. 50-doc search report (with excerpts) + PDF timing.
    ids = [int(r["id"]) for r in db.search_files(None, limit=args.search_limit)]
    if ids:
        d = svc.create_definition(ReportKind.SEARCH.value, "Search benchmark",
                                  query={"query": ""}, document_ids=ids,
                                  options={"excerpts": True})
        build("search_50", d, timed_pdf=not args.skip_pdf)
    else:
        report["skipped"]["search_50"] = "no documents"  # type: ignore[index]

    # B. 100-doc dynamic dossier, PII-masked, metadata only.
    try:
        dossier = DossierService(db).create_from_query(
            "M018 bench dossier", {"limit": args.dossier_limit},
            mode="DYNAMIC")
        d = svc.create_definition(ReportKind.DOSSIER.value, "Dossier benchmark",
                                  privacy_mode=PrivacyMode.MASK_PII.value,
                                  options={"dossier_id": dossier["dossier_id"], "excerpts": False})
        build("dossier_100", d)
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["dossier_100"] = type(exc).__name__

    # C. Timeline slice.
    try:
        build("timeline", svc.create_definition(
            ReportKind.TIMELINE.value, "Timeline benchmark",
            query={"start": "2000-01-01", "end": "2100-01-01"},
            options={"limit": 200}))
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["timeline"] = type(exc).__name__

    # D. Version family reconstruction.
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT file_id FROM version_members LIMIT 1").fetchone()
        if row is not None:
            from src.reports.citations import CitationRegistry
            t0 = time.perf_counter()
            pack = reconstruct_versions(db, int(row[0]), mode="FULL_LOCAL",
                                        registry=CitationRegistry())
            report["version_reconstruction"] = {
                "items": len(pack.items), "ordered": pack.ordered,
                "confidence": pack.confidence, "wall_s": round(time.perf_counter() - t0, 3)}
        else:
            report["skipped"]["version"] = "no families"  # type: ignore[index]
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["version"] = type(exc).__name__

    # E. Exact/duplicate report.
    try:
        from src.dedup import DedupStore
        groups = DedupStore(db).exact_duplicate_groups(max_groups=20)
        if groups:
            build("duplicates", svc.create_definition(
                ReportKind.DUPLICATES.value, "Duplicate benchmark",
                options={"min_size": 1, "max_groups": 20}))
        else:
            report["skipped"]["duplicates"] = "no exact groups"  # type: ignore[index]
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["duplicates"] = type(exc).__name__

    # F. Entity/category report.
    try:
        build("entity_category", svc.create_definition(
            ReportKind.ENTITY_CATEGORY.value, "Entity benchmark",
            options={"limit": 100}))
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["entity_category"] = type(exc).__name__

    # G. PII summary (masked).
    try:
        build("pii_summary", svc.create_definition(
            ReportKind.PII_SUMMARY.value, "PII benchmark",
            privacy_mode=PrivacyMode.MASK_PII.value))
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["pii_summary"] = type(exc).__name__

    # H. Email thread reconstruction/report.
    try:
        fid = _first_thread(db)
        if fid is not None:
            from src.reports.citations import CitationRegistry
            t0 = time.perf_counter()
            pack = reconstruct_email_thread(db, fid, mode="MASK_PII",
                                            registry=CitationRegistry())
            report["email_thread_reconstruction"] = {
                "messages": len(pack.items), "wall_s": round(time.perf_counter() - t0, 3)}
        else:
            report["skipped"]["email_thread"] = "no multi-message thread"  # type: ignore[index]
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["email_thread"] = type(exc).__name__

    # I. Ingestion report.
    try:
        build("ingestion", svc.create_definition(
            ReportKind.INGESTION.value, "Ingestion benchmark"))
    except Exception as exc:  # noqa: BLE001
        report["skipped"]["ingestion"] = type(exc).__name__

    report["wall_s"] = round(time.perf_counter() - t_all, 2)
    report["peak_rss_mb"] = _rss_mb()
    out_dir = Path(args.out_dir)
    report["output_bytes"] = _tree_size(out_dir) if out_dir.exists() else 0
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
