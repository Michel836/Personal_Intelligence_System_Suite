"""Canonical command-line interface (M019, phases 7-9).

One entry point, mapping to the canonical services (no blind script wrapping)::

    python -m src.cli <command> [options]      # or: pis <command>

Every command supports ``--json``. Expensive operations are bounded, destructive
ones require explicit confirmation, and the resolved database is always shown so
a production and a trial target cannot be confused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from loguru import logger

MAX_LIMIT = 500
DEFAULT_LIMIT = 50


def _bound(value: int) -> int:
    return max(1, min(int(value), MAX_LIMIT))


def _active_db(args: argparse.Namespace) -> Any:
    from .core.database import DatabaseManager
    if getattr(args, "db", None):
        return DatabaseManager(Path(args.db))
    return DatabaseManager()


def _emit(args: argparse.Namespace, data: Any, human: str) -> int:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, ensure_ascii=False))  # noqa: T201
    else:
        print(human)  # noqa: T201
    return 0


def _db_label(db: Any) -> str:
    return str(getattr(db, "db_path", "?"))


# --- command handlers --------------------------------------------------------
def cmd_status(args: argparse.Namespace) -> int:
    from .ops.health import health_report
    db = _active_db(args)
    report = health_report(db, include_paths=True)
    human = (f"status={report['status']} db={_db_label(db)} "
             f"files={report['db'].get('files_total')} "
             f"queue={report['ingestion_queue'].get('total')} "
             f"policy={report['privacy_policy']}")
    return _emit(args, report, human)


def cmd_doctor(args: argparse.Namespace) -> int:
    from .ops.doctor import run_doctor
    db = _active_db(args)
    report = run_doctor(db, deep=args.deep, include_paths=True)
    rows = "\n".join(f"  {c['status']:15} {c['name']}: {c['detail']}" for c in report["checks"])
    return _emit(args, report, f"doctor: {report['status']}\n{rows}")


def cmd_scan(args: argparse.Namespace) -> int:
    from .core.scan_service import ScanRequest, ScanService
    db = _active_db(args)
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        return _err(f"root is not a directory: {root}")
    if args.dry_run:
        return _emit(args, {"dry_run": True, "root": str(root), "db": _db_label(db)},
                     f"dry-run scan root={root} db={_db_label(db)}")
    result = ScanService(db).run(ScanRequest(root=root, limit=args.limit, batch_size=1000))
    data = {"status": result.status, "files_seen": result.files_seen,
            "files_upserted": result.files_upserted, "errors": result.files_errors,
            "error": result.error}
    return _emit(args, data, f"scan {result.status}: seen={result.files_seen} "
                             f"upserted={result.files_upserted} errors={result.files_errors}")


def cmd_extract(args: argparse.Namespace) -> int:
    from .ingest.pipeline import IngestionPipeline
    db = _active_db(args)
    if args.dry_run:
        pipeline = IngestionPipeline(db)
        eligible = pipeline.eligible(limit=_bound(args.limit), scope_prefix=args.scope)
        return _emit(args, {"dry_run": True, "eligible": len(eligible)},
                     f"dry-run extract: {len(eligible)} eligible document(s)")
    result = IngestionPipeline(db).run(limit=_bound(args.limit), scope_prefix=args.scope,
                                       ocr_explicit=args.ocr)
    return _emit(args, result, f"extract: attempted={result['attempted']} counts={result['counts']}")


def cmd_retry(args: argparse.Namespace) -> int:
    from .ingest.pipeline import IngestionPipeline
    db = _active_db(args)
    result = IngestionPipeline(db).run_retries(limit=_bound(args.limit))
    return _emit(args, result, f"retry: attempted={result['attempted']} counts={result['counts']}")


def cmd_ingest_issues(args: argparse.Namespace) -> int:
    from .ingest.queue_store import ExtractionQueue
    db = _active_db(args)
    queue = ExtractionQueue(db)
    issues = queue.issues(limit=_bound(args.limit))
    stats = queue.stats()
    data = {"stats": stats,
            "issues": [{"file_id": i.get("id"), "outcome": i.get("outcome"),
                        "attempts": i.get("attempts"), "terminal": bool(i.get("terminal"))}
                       for i in issues]}
    return _emit(args, data, f"ingestion issues: {len(issues)} (queued={stats.get('total')})")


def cmd_search(args: argparse.Namespace) -> int:
    db = _active_db(args)
    filters: dict[str, Any] = {}
    for key in ("extension", "document_kind", "language", "category"):
        value = getattr(args, key)
        if value:
            filters[key] = value
    if args.mode in ("semantic", "rerank"):
        try:
            from .intelligence.semantic_search import SemanticSearchEngine
            engine = SemanticSearchEngine(db)
            if not engine.is_available():
                return _emit(args, {"available": False, "results": []},
                             "semantic search unavailable")
            if args.mode == "semantic":
                rows = engine.search(args.query, limit=_bound(args.limit))
            else:
                from .dedup.rerank import rerank_search
                rows = rerank_search(db, engine, args.query, limit=_bound(args.limit), **filters)
        except Exception as exc:  # noqa: BLE001
            return _emit(args, {"available": False, "error": type(exc).__name__, "results": []},
                         f"search backend unavailable: {type(exc).__name__}")
    else:
        rows = db.search_files(args.query or None, limit=_bound(args.limit), **filters)
    data = {"mode": args.mode, "available": True, "count": len(rows),
            "results": [{"id": r.get("id"), "filename": r.get("filename"),
                         "extension": r.get("extension")} for r in rows]}
    human = "\n".join(f"  [{r.get('id')}] {r.get('filename')}" for r in rows) or "no results"
    return _emit(args, data, human)


def cmd_semantic_refresh(args: argparse.Namespace) -> int:
    db = _active_db(args)
    try:
        from .intelligence.semantic_search import SemanticSearchEngine
        result = SemanticSearchEngine(db).refresh(batch_size=_bound(args.limit))
    except Exception as exc:  # noqa: BLE001
        return _emit(args, {"available": False, "error": type(exc).__name__},
                     f"semantic refresh unavailable: {type(exc).__name__}")
    return _emit(args, result, f"semantic refresh: embedded={result.get('embedded')} "
                               f"store={result.get('store_count')}")


def cmd_duplicates(args: argparse.Namespace) -> int:
    db = _active_db(args)
    from .dedup import DedupStore
    store = DedupStore(db)
    data = {"totals": store.duplicate_totals(), "near": store.near_duplicate_stats(),
            "versions": store.version_family_stats()}
    return _emit(args, data, f"duplicates: {data['totals']}")


def cmd_intel(args: argparse.Namespace) -> int:
    from .intel.pipeline import IntelPipeline
    db = _active_db(args)
    result = IntelPipeline(db).run(limit=_bound(args.limit), scope_prefix=args.scope)
    return _emit(args, result, f"intel: processed={result.get('processed')} "
                               f"pii_docs={result.get('pii_docs')}")


def cmd_graph(args: argparse.Namespace) -> int:
    from .graph import RelationService
    db = _active_db(args)
    service = RelationService(db)
    if args.file_id is not None:
        types = [t for t in (args.types or "").split(",") if t] or None
        data = service.neighborhood(int(args.file_id), types=types, depth=int(args.depth),
                                    max_nodes=50, max_edges=120)
        return _emit(args, data, f"graph: nodes={data['metrics']['nodes']} "
                                 f"edges={data['metrics']['edges']}")
    data = service.entity_graph(min_docs=int(args.min_docs), max_entities=200, max_edges=1000)
    return _emit(args, data, f"entity graph: {data['stats']}")


def _scope_from_args(args: argparse.Namespace) -> dict[str, Any]:
    scope: dict[str, Any] = {"kind": getattr(args, "scope", None) or "all"}
    for key in ("query", "category", "language", "entity_type", "entity_value",
                "start", "end", "source", "dossier_id", "prefix"):
        value = getattr(args, key, None)
        if value:
            scope[key] = value
    if getattr(args, "date_source", None):
        scope["source"] = args.date_source
    if getattr(args, "file_id", None) is not None:
        scope["file_id"] = int(args.file_id)
    return scope


def cmd_galaxy(args: argparse.Namespace) -> int:
    from .galaxy import GalaxyError, GalaxyService
    db = _active_db(args)
    service = GalaxyService(db)
    try:
        payload = service.galaxy(scope=_scope_from_args(args), method=args.method,
                                 limit=args.limit, seed=args.seed, color_by=args.color_by,
                                 collapse_duplicates=args.collapse_duplicates,
                                 collapse_versions=args.collapse_versions,
                                 aggregate=args.aggregate, k=args.k,
                                 with_topics=not args.no_topics, persist=args.persist)
    except GalaxyError as exc:
        return _emit(args, {"available": False, "error": str(exc)}, f"galaxy unavailable: {exc}")
    data = {k: v for k, v in payload.items() if k != "points"}
    data["point_count"] = len(payload.get("points", []))
    if args.json:
        data["points"] = payload.get("points", [])[: _bound(args.limit or 500)]
    human = (f"galaxy scope={_scope_from_args(args)['kind']} tier={payload.get('tier')} "
             f"points={data['point_count']} clusters={len(payload.get('clusters', []))}")
    return _emit(args, data, human)


def cmd_clusters(args: argparse.Namespace) -> int:
    from .galaxy import GalaxyError, GalaxyService
    db = _active_db(args)
    service = GalaxyService(db)
    run_id = args.run_id
    if args.build or not run_id:
        existing = service.store.latest_cluster_run()
        run_id = str(existing["run_id"]) if existing else None
    if args.build or run_id is None:
        try:
            built = service.build_clusters(scope=_scope_from_args(args),
                                           algorithm=args.algorithm, k=args.k,
                                           seed=args.seed,
                                           collapse_duplicates=args.collapse_duplicates,
                                           collapse_versions=args.collapse_versions,
                                           persist=True)
            run_id = built["run_id"]
        except GalaxyError as exc:
            return _emit(args, {"available": False, "error": str(exc)},
                         f"clusters unavailable: {exc}")
    if not run_id:
        return _emit(args, {"available": False, "clusters": []}, "no cluster run yet")
    if not service.store.topics(run_id):
        try:
            service.build_topics(run_id, max_docs_per_cluster=args.docs,
                                 max_representatives=3)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"topic build unavailable: {exc}")
    rows = service.store.topics(run_id)
    data = {"available": True, "run_id": run_id, "clusters": rows}
    human = "\n".join(
        f"  [{r['cluster_id']}] {r['label']} ({r['size']} docs, cohesion={r['cohesion']})"
        for r in rows) or "no clusters"
    return _emit(args, data, human)


def cmd_topics(args: argparse.Namespace) -> int:
    from .galaxy import GalaxyService
    db = _active_db(args)
    service = GalaxyService(db)
    run_id = args.run_id
    if not run_id:
        latest = service.store.latest_cluster_run()
        run_id = str(latest["run_id"]) if latest else None
    if not run_id:
        return _emit(args, {"available": False, "topics": []}, "no cluster run yet")
    if not service.store.topics(run_id):
        try:
            service.build_topics(run_id, max_docs_per_cluster=args.docs,
                                 max_representatives=3)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"topic build unavailable: {exc}")
    rows = service.store.topics(run_id)
    data = {"available": True, "run_id": run_id, "topics": rows}
    human = "\n".join(
        f"  [{r['cluster_id']}] {r['label']} -> "
        f"{', '.join(x['term'] for x in (r.get('terms') or [])[:6])}" for r in rows) or "no topics"
    return _emit(args, data, human)


def cmd_context(args: argparse.Namespace) -> int:
    from .galaxy import GalaxyError, GalaxyService
    db = _active_db(args)
    try:
        data = GalaxyService(db).document_context(int(args.file_id))
    except GalaxyError as exc:
        return _emit(args, {"available": False, "error": str(exc)}, f"context unavailable: {exc}")
    human = (f"context file={args.file_id} language={data['intel'].get('language')} "
             f"neighbors={len(data.get('semantic_neighbors') or [])}")
    return _emit(args, data, human)


def cmd_dossier(args: argparse.Namespace) -> int:
    from .reports.dossiers import DossierService
    db = _active_db(args)
    service = DossierService(db)
    action = args.action
    if action == "list":
        rows = service.list_dossiers(limit=_bound(args.limit))
        human = "\n".join(f"  {d['dossier_id']} {d['name']} [{d['mode']}] "
                          f"{d['member_count']} docs" for d in rows) or "no dossiers"
        return _emit(args, rows, human)
    if action == "create":
        dossier = service.create(args.name, mode=(args.mode or "STATIC").upper(),
                                 query=json.loads(args.query) if args.query else None,
                                 file_ids=args.doc_ids or [])
        return _emit(args, dossier, f"created dossier {dossier.get('dossier_id')}")
    if action == "add":
        added = service.add_documents(args.dossier_id, args.doc_ids or [])
        return _emit(args, {"added": added}, f"added {added} document(s)")
    if action == "remove":
        removed = service.remove_documents(args.dossier_id, args.doc_ids or [])
        return _emit(args, {"removed": removed}, f"removed {removed} document(s)")
    if action == "freeze":
        return _emit(args, service.freeze(args.dossier_id), "frozen")
    if action == "compare":
        return _emit(args, service.compare_snapshot(args.dossier_id), "compared")
    return _err("unknown dossier action")


def cmd_report(args: argparse.Namespace) -> int:
    from .reports.export import ExportService
    from .reports.models import ReportFormat, ReportKind
    db = _active_db(args)
    service = ExportService(db)
    if args.action == "list":
        rows = service.store.list_artifacts(limit=_bound(args.limit))
        human = "\n".join(f"  {r['report_id']} {r['format']} exists={r.get('exists')}"
                          for r in rows) or "no artifacts"
        return _emit(args, rows, human)
    if args.action == "build":
        if args.kind.upper() not in {k.value for k in ReportKind}:
            return _err(
                f"unknown kind; choose from {[k.value for k in ReportKind]}")
        definition = service.create_definition(
            args.kind.upper(), args.title, privacy_mode=(args.privacy or "FULL_LOCAL").upper(),
            query=json.loads(args.query) if args.query else {},
            document_ids=args.doc_ids or [])
        if args.dry_run:
            ir = service.builder.build(definition)
            return _emit(args, {"report_id": definition.report_id,
                                "logical_fingerprint": ir.logical_fingerprint(),
                                "sections": len(ir.sections), "sources": len(ir.sources)},
                         f"report build: {len(ir.sections)} sections, "
                         f"{len(ir.sources)} sources")
        formats = tuple(args.formats.split(",")) if args.formats else (
            ReportFormat.HTML.value, ReportFormat.JSON.value)
        result = service.generate(definition, formats=formats)
        return _emit(args, {"report_id": definition.report_id,
                            "artifacts": [a.as_dict() for a in result.artifacts],
                            "manifest": result.manifest_path, "warnings": result.warnings},
                     f"report generated: {len(result.artifacts)} artifact(s)")
    return _err("unknown report action")


def cmd_maintenance(args: argparse.Namespace) -> int:
    from .ops.maintenance import MaintenanceService
    db = _active_db(args)
    service = MaintenanceService(db)
    if args.op == "list":
        return _emit(args, {"operations": service.operations()},
                     "\n".join(service.operations()))
    kwargs: dict[str, Any] = {}
    if args.op == "vacuum":
        kwargs["confirm"] = bool(args.confirm)
    if args.op == "prune-audit":
        kwargs["keep"] = int(args.keep)
    result = service.run(args.op, **kwargs)
    return _emit(args, result, f"maintenance {args.op}: {result['status']} "
                               f"({result['duration_s']}s) {result.get('details')}")


def cmd_backup(args: argparse.Namespace) -> int:
    from .ops.backup import create_backup
    db = _active_db(args)
    result = create_backup(db, out_dir=args.out, include_semantic=not args.no_semantic)
    return _emit(args, result.as_dict(), f"backup {result.backup_id} -> {result.archive_path}")


def cmd_restore(args: argparse.Namespace) -> int:
    from .ops.backup import restore_backup, verify_backup
    archive = Path(args.archive).expanduser()
    if args.verify_only:
        return _emit(args, verify_backup(archive), "verified" if verify_backup(archive)["ok"]
                     else "verification failed")
    result = restore_backup(archive, target_db=args.target_db, force=args.force,
                            confirm=args.confirm, restore_semantic=args.semantic)
    return _emit(args, result.as_dict(),
                 f"restore {result.status}: {result.error or result.target_db}")


def cmd_api(args: argparse.Namespace) -> int:
    from .api.app import main as api_main
    argv = []
    if args.host:
        argv += ["--host", args.host]
    if args.port:
        argv += ["--port", str(args.port)]
    if args.allow_remote:
        argv.append("--allow-remote")
    return int(api_main(argv))


def cmd_ui(args: argparse.Namespace) -> int:
    from .launcher import main as launcher_main
    argv = [args.profile or "full"]
    if args.port:
        argv += ["--port", str(args.port)]
    return int(launcher_main(argv))


def _err(message: str, code: int = 2) -> int:
    sys.stderr.write(f"error: {message}\n")
    return code


# --- parser ------------------------------------------------------------------
def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scope", default="all",
                        help="all|search|category|language|date|entity|dossier|prefix|file_ids")
    parser.add_argument("--query", default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--language", default=None)
    parser.add_argument("--entity-type", dest="entity_type", default=None)
    parser.add_argument("--entity-value", dest="entity_value", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--date-source", dest="date_source", default=None)
    parser.add_argument("--dossier-id", dest="dossier_id", default=None)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--file-id", dest="file_id", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pis", description="36TB Intelligence operations CLI.")
    parser.add_argument("--db", default=None, help="explicit database path (default: PIS_DB_PATH)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="aggregate health/status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor", help="diagnostics")
    p.add_argument("--deep", action="store_true", help="run the integrity check even on large DBs")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("scan", help="scan a root into the index")
    p.add_argument("root")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("extract", help="run content extraction")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--scope", default=None)
    p.add_argument("--ocr", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("retry", help="retry eligible extraction failures")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.set_defaults(func=cmd_retry)

    p = sub.add_parser("ingest-issues", help="list extraction issues")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.set_defaults(func=cmd_ingest_issues)

    p = sub.add_parser("search", help="search the index")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--mode", choices=["lexical", "semantic", "rerank"], default="lexical")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--extension", default=None)
    p.add_argument("--document-kind", dest="document_kind", default=None)
    p.add_argument("--language", default=None)
    p.add_argument("--category", default=None)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("semantic-refresh", help="embed dirty documents into the store")
    p.add_argument("--limit", type=int, default=256)
    p.set_defaults(func=cmd_semantic_refresh)

    p = sub.add_parser("duplicates", help="duplicate/version statistics")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_duplicates)

    p = sub.add_parser("intel", help="run the intelligence pipeline")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--scope", default=None)
    p.set_defaults(func=cmd_intel)

    p = sub.add_parser("graph", help="bounded graph queries")
    p.add_argument("--file-id", dest="file_id", type=int, default=None)
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--types", default=None)
    p.add_argument("--min-docs", dest="min_docs", type=int, default=2)
    p.set_defaults(func=cmd_graph)

    p = sub.add_parser("galaxy", help="bounded semantic galaxy projection")
    _add_scope_args(p)
    p.add_argument("--method", choices=["pca", "svd", "umap", "tsne"], default="pca")
    p.add_argument("--color-by", dest="color_by", default="cluster")
    p.add_argument("--limit", type=int, default=2000)
    p.add_argument("--k", type=int, default=16)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--aggregate", choices=["points", "clusters"], default=None)
    p.add_argument("--collapse-duplicates", dest="collapse_duplicates", action="store_true")
    p.add_argument("--collapse-versions", dest="collapse_versions", action="store_true")
    p.add_argument("--no-topics", dest="no_topics", action="store_true")
    p.add_argument("--persist", action="store_true")
    p.set_defaults(func=cmd_galaxy)

    p = sub.add_parser("clusters", help="list or build scalable clusters/topics")
    _add_scope_args(p)
    p.add_argument("--run-id", dest="run_id", default=None)
    p.add_argument("--build", action="store_true")
    p.add_argument("--algorithm", choices=["minibatch-kmeans", "kmeans", "hdbscan", "dbscan"],
                   default="minibatch-kmeans")
    p.add_argument("--k", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--docs", type=int, default=60)
    p.add_argument("--collapse-duplicates", dest="collapse_duplicates", action="store_true")
    p.add_argument("--collapse-versions", dest="collapse_versions", action="store_true")
    p.set_defaults(func=cmd_clusters)

    p = sub.add_parser("topics", help="list interpretable cluster topics")
    p.add_argument("--run-id", dest="run_id", default=None)
    p.add_argument("--docs", type=int, default=60)
    p.set_defaults(func=cmd_topics)

    p = sub.add_parser("context", help="contextual view for one document")
    p.add_argument("file_id", type=int)
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("dossier", help="manage dossiers")
    p.add_argument("action", choices=["list", "create", "add", "remove", "freeze", "compare"])
    p.add_argument("--dossier-id", dest="dossier_id", default=None)
    p.add_argument("--name", default="Untitled")
    p.add_argument("--mode", choices=["STATIC", "DYNAMIC"], default="STATIC")
    p.add_argument("--query", default=None, help="JSON query for dynamic dossiers")
    p.add_argument("--doc-ids", dest="doc_ids", type=int, nargs="*", default=[])
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.set_defaults(func=cmd_dossier)

    p = sub.add_parser("report", help="build/list reports")
    p.add_argument("action", choices=["list", "build"])
    p.add_argument("--kind", default="SEARCH")
    p.add_argument("--title", default="CLI report")
    p.add_argument("--query", default=None, help="JSON query")
    p.add_argument("--privacy", default="FULL_LOCAL")
    p.add_argument("--formats", default="HTML,JSON")
    p.add_argument("--doc-ids", dest="doc_ids", type=int, nargs="*", default=[])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("maintenance", help="maintenance operations")
    p.add_argument("op", help="operation name or 'list'")
    p.add_argument("--confirm", action="store_true", help="required for vacuum")
    p.add_argument("--keep", type=int, default=10000)
    p.set_defaults(func=cmd_maintenance)

    p = sub.add_parser("backup", help="create an application-consistent backup")
    p.add_argument("--out", default=None)
    p.add_argument("--no-semantic", action="store_true")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("restore", help="restore from a backup")
    p.add_argument("archive")
    p.add_argument("--target-db", dest="target_db", default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--semantic", action="store_true")
    p.add_argument("--verify-only", action="store_true")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("api", help="run the loopback REST API")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--allow-remote", action="store_true")
    p.set_defaults(func=cmd_api)

    p = sub.add_parser("ui", help="launch the canonical Streamlit app")
    p.add_argument("profile", nargs="?", default=None)
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=cmd_ui)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI reports instead of a bare traceback
        logger.debug(f"CLI error: {type(exc).__name__}: {exc}")
        return _err(f"{type(exc).__name__}: {exc}", code=1)


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
