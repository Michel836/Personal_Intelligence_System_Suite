"""Canonical command-line interface (M019, phases 7-9).

One entry point, mapping to the canonical services (no blind script wrapping)::

    python -m src.cli <command> [options]      # or: pis <command>

Every command supports ``--json``. Expensive operations are bounded, destructive
ones require explicit confirmation, and the resolved database is always shown so
a production and a trial target cannot be confused.

Exit codes (stable contract):

* ``0`` — success / complete;
* ``2`` — invalid input, hard failure or unexpected runtime error;
* ``3`` — partial success: scan completed with unreadable or excluded scopes,
  or an operation was cancelled.

The human-readable stream keeps stdout clean; the resolved database path is
printed on stderr (and in ``_meta`` for ``--json``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
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


def _emit(args: argparse.Namespace, data: Any, human: str, *, code: int = 0) -> int:
    if getattr(args, "json", False):
        payload = data
        if isinstance(data, dict):
            payload = {**data, "_meta": _meta(args)}
        print(json.dumps(payload, indent=2, ensure_ascii=False))  # noqa: T201
    else:
        print(human)  # noqa: T201
        sys.stderr.write(f"db: {_resolved_db_path(args)}\n")
    return int(code)


def _resolved_db_path(args: argparse.Namespace) -> str:
    """Return the resolved absolute database path without opening it."""
    from .core.paths import resolve_db_path

    try:
        return str(resolve_db_path(getattr(args, "db", None), migrate=False))
    except Exception:  # noqa: BLE001 - diagnostics must never break a command
        return str(getattr(args, "db", None) or "unknown")


def _meta(args: argparse.Namespace) -> dict[str, Any]:
    from .core.paths import data_dir

    return {
        "db": _resolved_db_path(args),
        "data_dir": str(data_dir()),
        "command": getattr(args, "command", None),
    }


def _db_label(db: Any) -> str:
    return str(getattr(db, "db_path", "?"))


# --- command handlers --------------------------------------------------------
def cmd_status(args: argparse.Namespace) -> int:
    from .ops.health import health_report
    db = _active_db(args)
    report = health_report(db, include_paths=True)
    coverage = report.get("semantic_coverage") or {}
    human = (f"status={report['status']} db={_db_label(db)} "
             f"files={report['db'].get('files_total')} "
             f"queue={report['ingestion_queue'].get('total')} "
             f"semantic={coverage.get('percent', 0)}% "
             f"({coverage.get('embedded', 0)}/{coverage.get('eligible', 0)}) "
             f"policy={report['privacy_policy']}")
    return _emit(args, report, human)


def cmd_doctor(args: argparse.Namespace) -> int:
    from .ops.doctor import run_doctor
    db = _active_db(args)
    report = run_doctor(db, deep=args.deep, include_paths=True)
    rows = "\n".join(f"  {c['status']:15} {c['name']}: {c['detail']}" for c in report["checks"])
    # ERROR is actionable (exit 2); WARN/NOT_CONFIGURED are informational.
    return _emit(args, report, f"doctor: {report['status']}\n{rows}",
                 code=2 if report["status"] == "ERROR" else 0)


def _scan_exit_code(status: str) -> int:
    """Stable scan exit-code contract: 0 complete, 3 partial, 2 failed."""
    if status == "COMPLETED":
        return 0
    if status in {"COMPLETED_WITH_WARNINGS", "CANCELLED"}:
        return 3
    return 2


def cmd_scan(args: argparse.Namespace) -> int:
    from .core.scan_service import ScanRequest, ScanService
    db = _active_db(args)
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        return _err(f"root is not a directory: {root}")
    if args.dry_run:
        return _emit(args, {"dry_run": True, "root": str(root), "db": _db_label(db)},
                     f"dry-run scan root={root} db={_db_label(db)}")
    env_excludes = [
        item.strip()
        for item in os.environ.get("PIS_SCAN_EXCLUDE_DIRS", "").split(",")
        if item.strip()
    ]
    result = ScanService(db).run(ScanRequest(
        root=root,
        limit=args.limit,
        batch_size=1000,
        ignore_errors=bool(args.ignore_errors),
        exclude_dirs=tuple(args.exclude_dirs or ()) + tuple(env_excludes),
        exclude_paths=tuple(args.exclude_paths or ()),
    ))
    data = {"status": result.status, "files_seen": result.files_seen,
            "files_upserted": result.files_upserted, "errors": result.files_errors,
            "unscanned_scopes": result.unscanned_scopes,
            "reconciled": result.reconciled,
            "warnings": result.warnings,
            "error": result.error}
    human = (f"scan {result.status}: seen={result.files_seen} "
             f"upserted={result.files_upserted} errors={result.files_errors} "
             f"unscanned_scopes={result.unscanned_scopes}")
    for warning in result.warnings:
        sys.stderr.write(f"warning: {warning}\n")
    return _emit(args, data, human, code=_scan_exit_code(result.status))


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
    from .ingest.taxonomy import RETRYABLE

    problems = sum(int(result["counts"].get(k, 0)) for k in RETRYABLE)
    problems += int(result["counts"].get("PERMANENT_ERROR", 0))
    return _emit(args, result,
                 f"extract: attempted={result['attempted']} counts={result['counts']}",
                 code=3 if problems else 0)


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
    """Foreground, bounded refresh (prefer ``pis embed`` for long runs)."""
    db = _active_db(args)
    try:
        from .intelligence.semantic_search import SemanticSearchEngine
        max_docs = None if getattr(args, "all", False) else _bound(args.limit)
        result = SemanticSearchEngine(db).refresh(
            batch_size=int(getattr(args, "batch_size", 256) or 256),
            max_docs=max_docs,
        )
    except Exception as exc:  # noqa: BLE001
        return _emit(args, {"available": False, "error": type(exc).__name__},
                     f"semantic refresh unavailable: {type(exc).__name__}", code=3)
    code = 0 if result.get("available") else 3
    return _emit(args, result, f"semantic refresh: embedded={result.get('embedded')} "
                               f"store={result.get('store_count')}", code=code)


def cmd_embed(args: argparse.Namespace) -> int:
    """Resumable semantic embedding job (foreground, background or status)."""
    from .intelligence.embedding_job import EmbeddingJob

    db = _active_db(args)
    job = EmbeddingJob(db)

    if args.status:
        data = job.status()
        coverage = data.get("coverage") or {}
        human = (f"embed status={data.get('status')} running={data.get('running')} "
                 f"coverage={coverage.get('percent', 0)}% "
                 f"({coverage.get('embedded', 0)}/{coverage.get('eligible', 0)}) "
                 f"pending={coverage.get('pending', 0)}")
        return _emit(args, data, human)

    if args.stop:
        result = job.request_stop()
        return _emit(args, result, "embed: stop requested")

    if args.rebuild:
        # Store loss/corruption or a migrated legacy DB: every tracked vector is
        # re-embedded from scratch (resumable like any other run).
        reset = db.reset_semantic_for_rebuild()
        sys.stderr.write(f"embed: rebuild requested ({reset} row(s) marked dirty)\n")

    if args.background:
        result = job.start_background(limit=args.limit or None,
                                      batch_size=args.batch_size)
        if result.get("started"):
            human = f"embed: background worker started pid={result.get('pid')} log={result.get('log')}"
            return _emit(args, result, human)
        human = f"embed: background start failed ({result.get('reason')})"
        if result.get("log_tail"):
            sys.stderr.write(str(result["log_tail"]) + "\n")
        return _emit(args, result, human, code=2)

    # ``--worker`` runs quietly under the detached parent; otherwise foreground.
    worker = bool(getattr(args, "worker", False))
    state = job.run(limit=args.limit or None, batch_size=args.batch_size)
    coverage = state.coverage or {}
    code = 0 if state.status == "DONE" else 3 if state.status == "STOPPED" else 2
    if worker:
        return code
    human = (f"embed {state.status}: processed={state.embedded} "
             f"coverage={coverage.get('percent', 0)}% "
             f"({coverage.get('embedded', 0)}/{coverage.get('eligible', 0)})")
    if state.error:
        human += f" error={state.error}"
    return _emit(args, asdict(state), human, code=code)


def cmd_hashes(args: argparse.Namespace) -> int:
    """Build exact-content hashes (and optional near-duplicate edges)."""
    from .dedup import DedupStore, ExactDuplicateEngine, NearDuplicateEngine

    db = _active_db(args)
    store = DedupStore(db)
    max_size = None if not args.max_size else int(args.max_size)
    hashed = ExactDuplicateEngine(db, store).hash_duplicate_candidates(
        min_size=int(args.min_size),
        max_size=max_size,
        scope_prefix=args.scope,
        include_members=not args.no_members,
        max_sizes=int(args.max_sizes),
    )
    data: dict[str, Any] = {"hashes": hashed, "totals": store.duplicate_totals()}
    if args.near:
        data["near"] = NearDuplicateEngine(db, store).build(
            threshold=float(args.threshold),
            scope_prefix=args.scope,
            max_docs=int(args.limit),
        )
    human = (f"hashes: hashed={hashed.get('hashed')} ok={hashed.get('ok')} "
             f"read={hashed.get('bytes_hashed', 0) / 1e9:.2f}GB "
             f"groups={data['totals'].get('groups')}")
    return _emit(args, data, human)


_DERIVED_STEPS = ("hashes", "intel", "embeddings", "clusters")


def cmd_derived(args: argparse.Namespace) -> int:
    """Build the canonical derived layers in dependency order."""
    from .dedup import DedupStore, ExactDuplicateEngine
    from .intel.pipeline import IntelPipeline

    db = _active_db(args)
    steps = [s.strip() for s in (args.only or ",".join(_DERIVED_STEPS)).split(",") if s.strip()]
    unknown = [s for s in steps if s not in _DERIVED_STEPS]
    if unknown:
        return _err(f"unknown derived step(s): {', '.join(unknown)}")
    limit = _bound(args.limit)
    results: dict[str, Any] = {}
    degraded = False

    if "hashes" in steps:
        results["hashes"] = ExactDuplicateEngine(db, DedupStore(db)).hash_duplicate_candidates(
            min_size=int(args.min_size), include_members=True, max_sizes=int(args.max_sizes)
        )
    if "intel" in steps:
        results["intel"] = IntelPipeline(db).run(limit=limit, scope_prefix=args.scope)
    if "embeddings" in steps:
        from .intelligence.semantic_search import SemanticSearchEngine

        refreshed = SemanticSearchEngine(db).refresh(
            batch_size=int(args.batch_size), max_docs=limit
        )
        results["embeddings"] = refreshed
        degraded = degraded or not refreshed.get("available")
    if "clusters" in steps:
        from .galaxy import GalaxyError, GalaxyService

        try:
            results["clusters"] = GalaxyService(db).build_clusters(
                scope={"kind": "all"}, persist=True
            )
        except GalaxyError as exc:
            results["clusters"] = {"available": False, "error": str(exc)}
            degraded = True

    human = "\n".join(
        f"  {name}: " + (f"error={value.get('error')}" if isinstance(value, dict) and value.get("error")
                         else "ok")
        for name, value in results.items()
    ) or "no steps"
    return _emit(args, {"steps": steps, "results": results, "degraded": degraded},
                 "derived:\n" + human, code=3 if degraded else 0)


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
    from .graph import DocumentGraph, RelationService
    db = _active_db(args)
    if args.file_id is not None:
        types = [t for t in (args.types or "").split(",") if t] or None
        data = DocumentGraph(db).neighborhood(int(args.file_id), types=types,
                                              depth=int(args.depth), max_nodes=50,
                                              max_edges=120)
        metrics = data.get("metrics", {})
        return _emit(args, data, f"graph: nodes={metrics.get('nodes')} "
                                 f"edges={metrics.get('edges')}")
    service = RelationService(db)
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
        requested = args.formats or (
            f"{ReportFormat.HTML.value},{ReportFormat.JSON.value}")
        formats = tuple(item.strip().upper() for item in requested.split(",") if item.strip())
        valid = {fmt.value for fmt in ReportFormat}
        unknown = [fmt for fmt in formats if fmt not in valid]
        if unknown or not formats:
            return _err(
                f"unknown report format(s): {', '.join(unknown) or '(none)'}; "
                f"choose from {sorted(valid)}"
            )
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


def cmd_migrate_data(args: argparse.Namespace) -> int:
    from .core.paths import migrate_legacy_data

    report = migrate_legacy_data(
        args.source,
        move=not args.copy,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    status = report.get("status")
    code = 2 if status in {"FAILED", "PARTIAL"} else 0
    human = (f"migrate-data {status}: {report.get('source')} -> "
             f"{report.get('target')} files={report.get('files', 0)} "
             f"bytes={report.get('bytes', 0)}")
    if report.get("errors"):
        human += f" errors={len(report['errors'])}"
    return _emit(args, report, human, code=code)


def _export_db_to_env(args: argparse.Namespace) -> None:
    """Make the resolved ``--db`` visible to in-process servers/launchers."""
    if getattr(args, "db", None):
        os.environ["PIS_DB_PATH"] = _resolved_db_path(args)


def cmd_api(args: argparse.Namespace) -> int:
    from .api.app import main as api_main

    _export_db_to_env(args)
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

    _export_db_to_env(args)
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
    parser.add_argument("-v", "--verbose", action="store_true", default=False,
                        help="verbose stderr logging (DEBUG)")
    parser.add_argument("-q", "--quiet", action="store_true", default=False,
                        help="errors only on stderr")
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
    p.add_argument(
        "--strict", dest="ignore_errors", action="store_false",
        help="fail closed on the first unreadable subtree (default: safe partial scan)",
    )
    p.add_argument(
        "--ignore-errors", dest="ignore_errors", action="store_true",
        help="record unreadable subtrees and finish COMPLETED_WITH_WARNINGS "
             "(default; reconciliation skips only those subtrees)",
    )
    p.add_argument(
        "--exclude", dest="exclude_dirs", action="append", default=[],
        metavar="PATTERN",
        help="exclude a directory basename/glob or path pattern (repeatable)",
    )
    p.add_argument(
        "--exclude-path", dest="exclude_paths", action="append", default=[],
        metavar="PATH",
        help="exclude an absolute path subtree (repeatable)",
    )
    p.set_defaults(
        func=cmd_scan,
        ignore_errors=os.environ.get("PIS_SCAN_IGNORE_ERRORS", "1").lower()
        not in {"0", "false", "no"},
    )

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

    p = sub.add_parser("semantic-refresh", help="bounded foreground semantic refresh")
    p.add_argument("--limit", type=int, default=256, help="max documents (default 256)")
    p.add_argument("--batch-size", dest="batch_size", type=int, default=256)
    p.add_argument("--all", action="store_true", help="embed every pending document")
    p.set_defaults(func=cmd_semantic_refresh)

    p = sub.add_parser("embed", help="resumable background semantic embedding job")
    action = p.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true",
                        help="show job state and semantic coverage")
    action.add_argument("--stop", action="store_true", help="request a clean stop")
    action.add_argument("--background", action="store_true",
                        help="start a detached worker (survives the terminal)")
    action.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--limit", type=int, default=0,
                   help="max documents for this run (0 = all pending)")
    p.add_argument("--batch-size", dest="batch_size", type=int, default=256)
    p.add_argument("--rebuild", action="store_true",
                   help="re-embed every tracked document from scratch "
                        "(after store loss, corruption or a legacy migration)")
    p.set_defaults(func=cmd_embed)

    p = sub.add_parser("hashes", help="build exact content hashes + duplicate groups")
    p.add_argument("--min-size", dest="min_size", type=int, default=1)
    p.add_argument("--max-size", dest="max_size", type=int, default=0,
                   help="max bytes to hash (0 = no upper bound)")
    p.add_argument("--max-sizes", dest="max_sizes", type=int, default=20000)
    p.add_argument("--scope", default=None, help="path prefix scope")
    p.add_argument("--no-members", dest="no_members", action="store_true",
                   help="physical files only (exclude archive members)")
    p.add_argument("--near", action="store_true", help="also build near-duplicate edges")
    p.add_argument("--threshold", type=float, default=0.9)
    p.add_argument("--limit", type=int, default=5000, help="max docs for --near")
    p.set_defaults(func=cmd_hashes)

    p = sub.add_parser("derived", help="build derived layers (hashes/intel/embeddings/clusters)")
    p.add_argument("--only", default=None,
                   help="comma-separated subset of hashes,intel,embeddings,clusters")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--batch-size", dest="batch_size", type=int, default=256)
    p.add_argument("--min-size", dest="min_size", type=int, default=1)
    p.add_argument("--max-sizes", dest="max_sizes", type=int, default=20000)
    p.add_argument("--scope", default=None)
    p.set_defaults(func=cmd_derived)

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

    p = sub.add_parser("migrate-data", help="migrate a legacy ./data tree to XDG")
    p.add_argument("--from", dest="source", default=None,
                   help="legacy data directory (default: ./data or repo data/)")
    p.add_argument("--copy", action="store_true",
                   help="keep the source tree (default: move after success)")
    p.add_argument("--overwrite", action="store_true",
                   help="overwrite existing target files")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_migrate_data)

    p = sub.add_parser("ui", help="launch the canonical Streamlit app")
    p.add_argument("profile", nargs="?", default=None)
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=cmd_ui)

    # Accept the global flags after the command too (``pis scan --json``), which
    # is what operators naturally type. ``SUPPRESS`` keeps the top-level value
    # when the flag is not repeated.
    for subparser in sub.choices.values():
        subparser.add_argument("--db", default=argparse.SUPPRESS,
                               help="explicit database path (default: PIS_DB_PATH)")
        subparser.add_argument("--json", action="store_true",
                               default=argparse.SUPPRESS,
                               help="emit machine-readable JSON")
        subparser.add_argument("-v", "--verbose", action="store_true",
                               default=argparse.SUPPRESS,
                               help="verbose stderr logging (DEBUG)")
        subparser.add_argument("-q", "--quiet", action="store_true",
                               default=argparse.SUPPRESS,
                               help="errors only on stderr")

    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    """Route library logs to stderr; keep stdout machine-readable."""
    if getattr(args, "verbose", False):
        level = "DEBUG"
    elif getattr(args, "quiet", False):
        level = "ERROR"
    else:
        level = os.environ.get("PIS_LOG_LEVEL", "WARNING").upper()
    def _stderr_sink(message) -> None:  # noqa: ANN001 - loguru message object
        stream = sys.stderr
        if stream is None:
            return
        try:
            stream.write(str(message))
        except (ValueError, OSError):
            # The stream may belong to a closed test capture; never raise here.
            pass

    logger.remove()
    logger.add(_stderr_sink, level=level,
               format="{level: <8} {name}: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI reports instead of a bare traceback
        logger.debug(f"CLI error: {type(exc).__name__}: {exc}")
        return _err(f"{type(exc).__name__}: {exc}", code=2)


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
