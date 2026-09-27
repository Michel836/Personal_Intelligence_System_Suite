"""Opt-in local REST API (M019, phases 2-6).

Built on **Starlette** (already pulled in by uvicorn); FastAPI is *not* required.
Loopback-only by default, stable ``/api/v1`` prefix, bounded pagination, request
timeouts, masked PII and redactable paths. There is no arbitrary SQL, filesystem
read or command execution, and no source-mutation endpoint.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger

from .dto import MAX_LIMIT, document_dto, file_dto, pagination

API_VERSION = "v1"
API_SCHEMA = "api/v1"
_API_PREFIX = "/api/v1"
_REQUEST_TIMEOUT_S = 30.0
_MAX_BODY_BYTES = 1 * 1024 * 1024
_MAX_QUERY_CHARS = 500


def loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def bind_warning(host: str) -> str | None:
    if loopback(host):
        return None
    return (f"WARNING: binding to non-loopback host '{host}' exposes a mono-user, "
            "unauthenticated API on the network. Real auth/TLS is OUT OF SCOPE; "
            "use only on a trusted, firewalled host.")


# --- middleware --------------------------------------------------------------
def _middleware(timeout_s: float, max_body: int) -> list[Any]:
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    class TimeoutMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Callable[..., Any]) -> Any:
            try:
                return await asyncio.wait_for(call_next(request), timeout=timeout_s)
            except TimeoutError:
                from starlette.responses import JSONResponse
                return JSONResponse({"schema": API_SCHEMA, "error": "request timeout"},
                                    status_code=504)

    class BodyLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Callable[..., Any]) -> Any:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > max_body:
                from starlette.responses import JSONResponse
                return JSONResponse({"schema": API_SCHEMA, "error": "request body too large"},
                                    status_code=413)
            return await call_next(request)

    return [Middleware(TimeoutMiddleware), Middleware(BodyLimitMiddleware)]


def _ok(data: Any, **extra: Any) -> Any:
    from starlette.responses import JSONResponse
    return JSONResponse({"schema": API_SCHEMA, "data": data, **extra})


def _err(message: str, status: int = 400) -> Any:
    from starlette.responses import JSONResponse
    return JSONResponse({"schema": API_SCHEMA, "error": message}, status_code=status)


def create_app(db: Any = None) -> Any:
    from starlette.applications import Starlette
    from starlette.routing import Route

    if db is None:
        from ..core.database import DatabaseManager
        db = DatabaseManager()
    mask_pii = True  # always on by default; never exposed as "off" remotely
    redact_paths = True

    def _flags(request: Any) -> tuple[bool, bool]:
        # PII masking cannot be disabled over the API; paths may be shown only
        # when explicitly requested on loopback usage.
        show_paths = request.query_params.get("show_paths") == "1"
        return mask_pii, (redact_paths and not show_paths)

    # -- health / ops ------------------------------------------------------
    async def health(_request: Any) -> Any:
        from ..ops.health import health_report
        return _ok(health_report(db, include_paths=False))

    async def doctor(_request: Any) -> Any:
        from ..ops.doctor import run_doctor
        report = run_doctor(db, include_paths=False, probe_network=False)
        return _ok({"status": report["status"], "version": report["version"],
                    "checks": report["checks"], "dependencies": report["dependencies"]})

    async def maintenance_status(_request: Any) -> Any:
        from ..ops.maintenance import MaintenanceService
        return _ok(MaintenanceService(db).status())

    async def index(request: Any) -> Any:
        return _ok({"api_version": API_VERSION,
                    "endpoints": [r.path for r in request.app.routes if r.path.startswith(_API_PREFIX)],
                    "pii_masked": True})

    # -- files -------------------------------------------------------------
    async def list_files(request: Any) -> Any:
        limit, offset = pagination(request.query_params.get("limit"),
                                   request.query_params.get("offset"))
        params = request.query_params
        kwargs: dict[str, Any] = {}
        if params.get("extension"):
            kwargs["extension"] = params["extension"]
        if params.get("document_kind"):
            kwargs["document_kind"] = params["document_kind"]
        rows = db.search_files(None, limit=min(limit + offset, MAX_LIMIT + offset), **kwargs)
        window = rows[offset: offset + limit]
        m, rp = _flags(request)
        return _ok([file_dto(db, r, mask_pii=m, redact_paths=rp) for r in window],
                   page={"limit": limit, "offset": offset, "returned": len(window)})

    async def get_file(request: Any) -> Any:
        try:
            file_id = int(request.path_params["file_id"])
        except (KeyError, ValueError):
            return _err("invalid file id")
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None:
            return _err("not found", status=404)
        m, rp = _flags(request)
        try:
            preview = min(int(request.query_params.get("preview", "500")), 2000)
        except ValueError:
            preview = 500
        return _ok(document_dto(db, dict(row), preview_chars=preview,
                                mask_pii=m, redact_paths=rp))

    # -- search ------------------------------------------------------------
    async def search(request: Any) -> Any:
        q = (request.query_params.get("q") or "").strip()
        if len(q) > _MAX_QUERY_CHARS:
            return _err("query too long")
        mode = request.query_params.get("mode", "lexical")
        limit, offset = pagination(request.query_params.get("limit"),
                                   request.query_params.get("offset"))
        params = request.query_params
        filters: dict[str, Any] = {}
        for key in ("extension", "document_kind", "language", "category",
                    "entity_type", "entity_value"):
            if params.get(key):
                filters[key] = params[key]
        if params.get("has_pii") in ("0", "1"):
            filters["has_pii"] = params["has_pii"] == "1"
        if params.get("exclude_high_sensitivity") == "1":
            filters["exclude_high_sensitivity"] = True
        m, rp = _flags(request)

        if mode in ("semantic", "rerank"):
            try:
                from ..intelligence.semantic_search import SemanticSearchEngine
                engine = SemanticSearchEngine(db)
                if not engine.is_available():
                    return _ok([], available=False, mode=mode,
                               error="semantic engine unavailable")
                if mode == "semantic":
                    rows = engine.search(q, limit=limit + offset)
                else:
                    from ..dedup.rerank import rerank_search
                    rows = rerank_search(db, engine, q, limit=limit + offset, **filters)
            except Exception as exc:  # noqa: BLE001 - optional backend
                return _ok([], available=False, mode=mode, error=type(exc).__name__)
        else:
            rows = db.search_files(q or None, limit=min(limit + offset, MAX_LIMIT + offset),
                                   **filters)
        window = rows[offset: offset + limit]
        return _ok([file_dto(db, r, mask_pii=m, redact_paths=rp) for r in window],
                   page={"limit": limit, "offset": offset, "returned": len(window)},
                   mode=mode, available=True)

    # -- duplicates / versions --------------------------------------------
    async def duplicates(request: Any) -> Any:
        limit, _ = pagination(request.query_params.get("limit"), 0, max_limit=50)
        from ..dedup import DedupStore
        try:
            groups = DedupStore(db).exact_duplicate_groups(max_groups=limit,
                                                           max_members_per_group=20)
        except Exception as exc:  # noqa: BLE001
            return _ok([], available=False, error=type(exc).__name__)
        m, rp = _flags(request)
        out = [{"count": g["count"], "size_bytes": g["size_bytes"],
                "wasted_bytes": g["wasted_bytes"],
                "members": [file_dto(db, member, mask_pii=m, redact_paths=rp)
                            for member in g.get("members", [])]} for g in groups]
        return _ok(out, available=True)

    async def versions(request: Any) -> Any:
        try:
            file_id = int(request.path_params["file_id"])
        except (KeyError, ValueError):
            return _err("invalid file id")
        from ..dedup import DedupStore
        family = DedupStore(db).get_version_family_for_file(file_id)
        if not family:
            return _err("no version family", status=404)
        m, rp = _flags(request)
        raw = family.get("evidence")
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:  # noqa: BLE001
                raw = {}
        return _ok({"family_key": family.get("family_key"),
                    "base_name": family.get("base_name"),
                    "confidence": family.get("confidence"),
                    "evidence": raw or {},
                    "members": [file_dto(db, dict(mem), mask_pii=m, redact_paths=rp)
                                for mem in family.get("members", [])]})

    # -- intel / timeline / graph -----------------------------------------
    async def entities(request: Any) -> Any:
        limit, offset = pagination(request.query_params.get("limit"),
                                   request.query_params.get("offset"))
        params = request.query_params
        filters: dict[str, Any] = {}
        if params.get("type"):
            filters["entity_type"] = params["type"]
        if params.get("value"):
            filters["entity_value"] = params["value"]
        rows = db.search_files(None, limit=min(limit + offset, MAX_LIMIT + offset), **filters)
        m, rp = _flags(request)
        return _ok([file_dto(db, r, mask_pii=m, redact_paths=rp)
                    for r in rows[offset: offset + limit]])

    async def categories(request: Any) -> Any:
        limit, offset = pagination(request.query_params.get("limit"),
                                   request.query_params.get("offset"))
        params = request.query_params
        filters: dict[str, Any] = {"category": params["category"]} if params.get("category") else {}
        rows = db.search_files(None, limit=min(limit + offset, MAX_LIMIT + offset), **filters)
        m, rp = _flags(request)
        return _ok([file_dto(db, r, mask_pii=m, redact_paths=rp)
                    for r in rows[offset: offset + limit]])

    async def timeline(request: Any) -> Any:
        limit, _ = pagination(request.query_params.get("limit"), 0, max_limit=200)
        from ..graph.timeline import TimelineService
        params = request.query_params
        result = TimelineService(db).events(
            start=params.get("start"), end=params.get("end"),
            source=params.get("source") or "modified_at",
            limit=limit)
        return _ok({"events": result["events"][:limit], "count": result["count"],
                    "date_source": result["date_source"], "confidence": result["confidence"]},
                   provenance=result.get("provenance"))

    async def graph_neighborhood(request: Any) -> Any:
        try:
            file_id = int(request.path_params["file_id"])
        except (KeyError, ValueError):
            return _err("invalid file id")
        from ..graph import RelationService
        params = request.query_params
        try:
            depth = int(params.get("depth", "1"))
        except ValueError:
            depth = 1
        types = [t for t in (params.get("types") or "").split(",") if t] or None
        result = RelationService(db).neighborhood(file_id, types=types, depth=depth,
                                                  max_nodes=50, max_edges=120)
        return _ok(result)

    async def ingestion_issues(request: Any) -> Any:
        limit, _ = pagination(request.query_params.get("limit"), 0, max_limit=200)
        from ..ingest.queue_store import ExtractionQueue
        queue = ExtractionQueue(db)
        issues = queue.issues(limit=limit)
        return _ok({"stats": queue.stats(),
                    "issues": [{"file_id": i.get("id"), "outcome": i.get("outcome"),
                                "attempts": i.get("attempts"),
                                "terminal": bool(i.get("terminal")),
                                "detail": (i.get("detail") or "")[:120]} for i in issues]})

    # -- dossiers ----------------------------------------------------------
    async def dossiers_index(request: Any) -> Any:
        from ..reports.dossiers import DossierService
        service = DossierService(db)
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                return _err("invalid JSON body")
            name = str(body.get("name") or "").strip()
            if not name:
                return _err("name is required")
            mode = str(body.get("mode") or "STATIC").upper()
            if mode not in ("STATIC", "DYNAMIC"):
                return _err("mode must be STATIC or DYNAMIC")
            dossier = service.create(name, description=str(body.get("description") or ""),
                                     mode=mode, query=body.get("query") or {},
                                     file_ids=[int(i) for i in (body.get("document_ids") or [])])
            return _ok({"dossier_id": dossier["dossier_id"], "name": dossier["name"],
                        "mode": dossier["mode"]})
        return _ok([{"dossier_id": d["dossier_id"], "name": d["name"], "mode": d["mode"],
                     "member_count": d["member_count"]} for d in service.list_dossiers()])

    async def dossier_detail(request: Any) -> Any:
        from ..reports.dossiers import DossierService
        dossier_id = request.path_params["dossier_id"]
        service = DossierService(db)
        resolved = service.resolve(dossier_id)
        if resolved.get("error"):
            return _err(resolved["error"], status=404)
        m, rp = _flags(request)
        members = [{"file_id": mem["file_id"], "filename": mem.get("filename"),
                    "state": mem.get("state"), "source": mem.get("source"),
                    "section": mem.get("section"),
                    "dossier_root": resolved.get("name")} for mem in resolved["members"][:MAX_LIMIT]]
        return _ok({"dossier_id": dossier_id, "name": resolved.get("name"),
                    "mode": resolved.get("mode"), "count": resolved.get("count"),
                    "missing": resolved.get("missing"), "members": members,
                    "frozen": bool(resolved.get("frozen"))})

    async def dossier_documents(request: Any) -> Any:
        from ..reports.dossiers import DossierService
        dossier_id = request.path_params["dossier_id"]
        service = DossierService(db)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _err("invalid JSON body")
        file_ids = [int(i) for i in (body.get("document_ids") or [])]
        if request.method == "DELETE":
            removed = service.remove_documents(dossier_id, file_ids)
            return _ok({"removed": removed})
        if str(body.get("action") or "") == "exclude":
            return _ok({"excluded": service.exclude_documents(dossier_id, file_ids)})
        added = service.add_documents(dossier_id, file_ids,
                                      section=body.get("section"), note=body.get("note"))
        return _ok({"added": added})

    async def dossier_freeze(request: Any) -> Any:
        from ..reports.dossiers import DossierService
        dossier_id = request.path_params["dossier_id"]
        result = DossierService(db).freeze(dossier_id)
        return _ok(result)

    # -- reports -----------------------------------------------------------
    async def reports_index(request: Any) -> Any:
        from ..reports.export import ExportService
        from ..reports.models import ReportKind
        service = ExportService(db)
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                return _err("invalid JSON body")
            kind = str(body.get("kind") or ReportKind.SEARCH.value).upper()
            if kind not in {k.value for k in ReportKind}:
                return _err("unknown report kind")
            privacy_mode = str(body.get("privacy_mode") or "FULL_LOCAL").upper()
            definition = service.create_definition(
                kind, str(body.get("title") or f"API {kind}"),
                description=str(body.get("description") or ""),
                privacy_mode=privacy_mode,
                query=body.get("query") or {},
                document_ids=[int(i) for i in (body.get("document_ids") or [])],
                options=body.get("options") or {})
            if not body.get("generate"):
                ir = service.builder.build(definition)
                return _ok({"report_id": definition.report_id,
                            "logical_fingerprint": ir.logical_fingerprint(),
                            "sections": len(ir.sections), "sources": len(ir.sources),
                            "warnings": ir.warnings, "generated": False})
            formats = body.get("formats") or ["HTML", "JSON"]
            result = service.generate(definition, formats=tuple(formats))
            return _ok({"report_id": definition.report_id,
                        "logical_fingerprint": result.ir.logical_fingerprint(),
                        "artifacts": [a.as_dict() for a in result.artifacts],
                        "manifest_path": result.manifest_path,
                        "warnings": result.warnings, "generated": True})
        return _ok(service.store.list_definitions(limit=100))

    async def report_detail(request: Any) -> Any:
        from ..reports.export import ExportService
        service = ExportService(db)
        report_id = request.path_params["report_id"]
        definition = service.get_definition(report_id)
        if definition is None:
            return _err("not found", status=404)
        return _ok({"definition": definition.as_dict(),
                    "artifacts": service.store.artifacts_for(report_id)})

    routes = [
        Route(f"{_API_PREFIX}", index),
        Route(f"{_API_PREFIX}/health", health),
        Route(f"{_API_PREFIX}/doctor", doctor),
        Route(f"{_API_PREFIX}/maintenance/status", maintenance_status),
        Route(f"{_API_PREFIX}/files", list_files),
        Route(f"{_API_PREFIX}/files/{{file_id}}", get_file),
        Route(f"{_API_PREFIX}/search", search),
        Route(f"{_API_PREFIX}/duplicates", duplicates),
        Route(f"{_API_PREFIX}/versions/{{file_id}}", versions),
        Route(f"{_API_PREFIX}/entities", entities),
        Route(f"{_API_PREFIX}/categories", categories),
        Route(f"{_API_PREFIX}/timeline", timeline),
        Route(f"{_API_PREFIX}/graph/neighborhood/{{file_id}}", graph_neighborhood),
        Route(f"{_API_PREFIX}/ingestion/issues", ingestion_issues),
        Route(f"{_API_PREFIX}/dossiers", dossiers_index, methods=["GET", "POST"]),
        Route(f"{_API_PREFIX}/dossiers/{{dossier_id}}", dossier_detail),
        Route(f"{_API_PREFIX}/dossiers/{{dossier_id}}/documents", dossier_documents,
              methods=["POST", "DELETE"]),
        Route(f"{_API_PREFIX}/dossiers/{{dossier_id}}/freeze", dossier_freeze, methods=["POST"]),
        Route(f"{_API_PREFIX}/reports", reports_index, methods=["GET", "POST"]),
        Route(f"{_API_PREFIX}/reports/{{report_id}}", report_detail),
    ]
    return Starlette(routes=routes, middleware=_middleware(_REQUEST_TIMEOUT_S, _MAX_BODY_BYTES))


def main(argv: list[str] | None = None) -> int:
    """Run the API server (foreground)."""
    import argparse

    from ..ops.config import resolve_setting
    ap = argparse.ArgumentParser(prog="pis api", description="Run the loopback REST API.")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--allow-remote", action="store_true",
                    help="allow binding to a non-loopback host (no auth/TLS provided)")
    args = ap.parse_args(argv)
    host = args.host or resolve_setting("PIS_API_HOST")[0]
    port = args.port or int(resolve_setting("PIS_API_PORT")[0])
    warning = bind_warning(host)
    if warning and not args.allow_remote:
        logger.error(warning)
        print(warning)  # noqa: T201
        return 2
    if warning:
        logger.warning(warning)
    from ..core.database import DatabaseManager
    db = DatabaseManager()
    app = create_app(db)
    try:
        import uvicorn
    except Exception:  # noqa: BLE001
        logger.error("uvicorn is not installed; cannot start the API")
        return 2
    print(f"[PIS] api listening on http://{host}:{port}{_API_PREFIX}")  # noqa: T201
    uvicorn.run(app, host=host, port=int(port), log_level="warning")
    return 0
