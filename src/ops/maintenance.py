"""Canonical maintenance service (M019, phases 12-13).

Every operation is bounded, timed, logged and reportable. ``VACUUM`` is never run
implicitly: it requires an explicit ``confirm=True`` and a free-space precheck.
Routine upkeep prefers ``PRAGMA optimize`` / ``ANALYZE``.
"""
from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from .dbutil import db_size, has_table, page_stats
from .schema import ensure_user_version

#: Tables whose file_id must reference an existing row in ``files``.
_FILE_REF_TABLES = (
    "content_hashes", "doc_language", "doc_entities", "doc_categories", "doc_pii",
    "semantic_state", "extraction_queue", "email_threads", "dossier_documents",
    "version_members", "near_duplicate_edges",
)


class MaintenanceService:
    def __init__(self, db: Any) -> None:
        self.db = db

    # -- result helper -----------------------------------------------------
    @staticmethod
    def _result(op: str, status: str, seconds: float, details: dict[str, Any],
                warnings: list[str] | None = None) -> dict[str, Any]:
        return {"op": op, "status": status, "duration_s": round(seconds, 4),
                "details": details, "warnings": warnings or []}

    def _run(self, op: str, fn: Callable[[], tuple[str, dict[str, Any], list[str]]]) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            status, details, warnings = fn()
        except Exception as exc:  # noqa: BLE001 - maintenance must report, not crash
            logger.warning(f"M019 maintenance {op} failed: {type(exc).__name__}")
            return self._result(op, "ERROR", time.perf_counter() - t0,
                                {"error": type(exc).__name__, "message": str(exc)[:200]})
        result = self._result(op, status, time.perf_counter() - t0, details, warnings)
        logger.info(f"M019 maintenance {op}: {status} in {result['duration_s']}s")
        return result

    # -- integrity / optimize ---------------------------------------------
    def integrity_check(self, *, limit_errors: int = 100) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            with self.db.get_connection() as conn:
                rows = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
            ok = rows == ["ok"]
            return ("OK" if ok else "ERROR",
                    {"errors": rows[:limit_errors], "error_count": 0 if ok else len(rows)},
                    [] if ok else ["integrity check reported errors"])
        return self._run("integrity", fn)

    def analyze(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            t = time.perf_counter()
            with self.db.get_connection() as conn:
                conn.execute("ANALYZE")
                conn.commit()
            return "OK", {"analyze_s": round(time.perf_counter() - t, 4)}, []
        return self._run("analyze", fn)

    def optimize(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            with self.db.get_connection() as conn:
                conn.execute("PRAGMA optimize")
                conn.commit()
            return "OK", {}, []
        return self._run("optimize", fn)

    def checkpoint(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            with self.db.get_connection() as conn:
                row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            return "OK", {"busy": row[0], "log_pages": row[1], "checkpointed": row[2]}, []
        return self._run("checkpoint", fn)

    def vacuum_precheck(self, *, safety_factor: float = 1.1) -> dict[str, Any]:
        stats = page_stats(self.db)
        size = db_size(self.db)
        free = shutil.disk_usage(Path(self.db.db_path).parent).free
        needed = int(size * safety_factor) + 16 * 1024 * 1024
        return {"db_size_bytes": size, "free_bytes": free, "needed_bytes": needed,
                "enough_space": free >= needed, "reclaimable_bytes": stats["reclaimable_bytes"],
                "journal_mode": stats["journal_mode"],
                "recommend_backup": True}

    def vacuum(self, *, confirm: bool = False) -> dict[str, Any]:
        precheck = self.vacuum_precheck()
        if not confirm:
            return self._result("vacuum", "SKIPPED", 0.0,
                                {"precheck": precheck, "reason": "confirmation required"}, [])
        if not precheck["enough_space"]:
            return self._result("vacuum", "ERROR", 0.0,
                                {"precheck": precheck, "reason": "insufficient free space"}, [])

        def fn() -> tuple[str, dict[str, Any], list[str]]:
            t = time.perf_counter()
            with self.db.get_connection() as conn:
                conn.execute("VACUUM")
            after = db_size(self.db)
            return "OK", {"before_bytes": precheck["db_size_bytes"], "after_bytes": after,
                          "vacuum_s": round(time.perf_counter() - t, 3)}, []
        return self._run("vacuum", fn)

    # -- FTS ---------------------------------------------------------------
    @staticmethod
    def _indexed_count(conn: Any) -> int | None:
        """Indexed row count from the FTS5 shadow ``_docsize`` table.

        For an external-content FTS5 table ``COUNT(*) FROM files_fts`` reads the
        content table, so it cannot detect an unindexed row. The shadow
        ``_docsize`` table has exactly one row per *indexed* document.
        """
        try:
            return int(conn.execute("SELECT COUNT(*) FROM files_fts_docsize").fetchone()[0])
        except Exception:  # noqa: BLE001 - shadow table name/version differs
            return None

    def fts_consistency(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            with self.db.get_connection() as conn:
                files = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
                indexed = self._indexed_count(conn)
            consistent = indexed is None or indexed == files
            return ("OK" if consistent else "WARN",
                    {"files": files, "indexed": indexed, "consistent": consistent},
                    [] if consistent else ["run 'fts-rebuild'"])
        return self._run("fts-consistency", fn)

    def fts_rebuild(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            t = time.perf_counter()
            with self.db.get_connection() as conn:
                conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
                conn.commit()
                files = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
                indexed = self._indexed_count(conn)
            consistent = indexed is None or indexed == files
            return ("OK" if consistent else "WARN",
                    {"files": files, "indexed": indexed, "consistent": consistent,
                     "rebuild_s": round(time.perf_counter() - t, 3)},
                    [] if consistent else ["index still inconsistent after rebuild"])
        return self._run("fts-rebuild", fn)

    # -- pruning -----------------------------------------------------------
    def prune_stale_relations(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            details: dict[str, Any] = {}
            if has_table(self.db, "version_members"):
                from ..dedup import DedupStore
                details.update(DedupStore(self.db).prune_missing_relations())
            if has_table(self.db, "extraction_queue"):
                from ..ingest.queue_store import ExtractionQueue
                details["queue_rows_pruned"] = ExtractionQueue(self.db).prune_missing()
            return "OK", details, []
        return self._run("prune-relations", fn)

    def prune_intel(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            if not any(has_table(self.db, t) for t in
                       ("doc_language", "doc_entities", "doc_categories", "doc_pii")):
                return "SKIPPED", {"reason": "no intelligence tables"}, []
            from ..intel import IntelStore
            return "OK", IntelStore(self.db).prune_removed(), []
        return self._run("prune-intel", fn)

    def prune_artifacts(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            if not has_table(self.db, "report_artifacts"):
                return "SKIPPED", {"reason": "no report tables"}, []
            from ..reports.store import ReportStore
            return "OK", {"removed": ReportStore(self.db).prune_missing_artifacts()}, []
        return self._run("prune-artifacts", fn)

    def prune_audit(self, *, keep: int = 10000) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            if not has_table(self.db, "audit_events"):
                return "SKIPPED", {"reason": "no audit table"}, []
            from ..intel import IntelStore
            return "OK", {"removed": IntelStore(self.db).prune_audit(keep=keep)}, []
        return self._run("prune-audit", fn)

    # -- consistency -------------------------------------------------------
    def orphan_scan(self, *, limit: int = 1000) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            findings: dict[str, Any] = {}
            warnings: list[str] = []
            with self.db.get_connection() as conn:
                for table in _FILE_REF_TABLES:
                    if not has_table(self.db, table):
                        continue
                    column = "src_id" if table == "near_duplicate_edges" else "file_id"
                    try:
                        n = int(conn.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE {column} NOT IN "
                            f"(SELECT id FROM files) LIMIT ?", (int(limit),)).fetchone()[0])
                    except Exception:  # noqa: BLE001
                        continue
                    if n:
                        findings[table] = n
                        warnings.append(f"{n} orphan row(s) in {table}")
            return ("OK" if not findings else "WARN", {"orphans": findings}, warnings)
        return self._run("orphan-scan", fn)

    def semantic_consistency(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            from .health import semantic_status
            status = semantic_status()
            store_counts = {s["model_key"]: int(s.get("count") or 0) for s in status["stores"]}
            total_vectors = sum(store_counts.values())
            embedded = dirty = 0
            if has_table(self.db, "semantic_state"):
                with self.db.get_connection() as conn:
                    embedded = int(conn.execute(
                        "SELECT COUNT(*) FROM semantic_state WHERE embedded_version IS NOT NULL "
                        "AND prune=0").fetchone()[0])
                    dirty = int(conn.execute(
                        "SELECT COUNT(*) FROM semantic_state WHERE dirty=1").fetchone()[0])
            consistent = total_vectors == embedded or total_vectors == 0
            warnings = [] if consistent else [
                f"store vectors ({total_vectors}) != embedded rows ({embedded})"]
            return ("OK" if consistent else "WARN",
                    {"store_vectors": total_vectors, "embedded_rows": embedded,
                     "dirty_rows": dirty, "consistent": consistent, "stores": store_counts},
                    warnings)
        return self._run("semantic-consistency", fn)

    def schema_init(self) -> dict[str, Any]:
        def fn() -> tuple[str, dict[str, Any], list[str]]:
            version = ensure_user_version(self.db)
            return "OK", {"user_version": version}, []
        return self._run("schema-init", fn)

    # -- status ------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "db": page_stats(self.db),
            "db_size_bytes": db_size(self.db),
            "fts": self.fts_consistency()["details"],
            "vacuum_precheck": self.vacuum_precheck(),
        }

    # -- dispatcher --------------------------------------------------------
    def run(self, op: str, **kwargs: Any) -> dict[str, Any]:
        ops: dict[str, Callable[..., dict[str, Any]]] = {
            "integrity": self.integrity_check,
            "analyze": self.analyze,
            "optimize": self.optimize,
            "checkpoint": self.checkpoint,
            "vacuum": self.vacuum,
            "vacuum-precheck": self.vacuum_precheck,
            "fts-consistency": self.fts_consistency,
            "fts-rebuild": self.fts_rebuild,
            "prune-relations": self.prune_stale_relations,
            "prune-intel": self.prune_intel,
            "prune-artifacts": self.prune_artifacts,
            "prune-audit": self.prune_audit,
            "orphan-scan": self.orphan_scan,
            "semantic-consistency": self.semantic_consistency,
            "schema-init": self.schema_init,
            "status": self.status,
        }
        fn = ops.get(op)
        if fn is None:
            return {"op": op, "status": "ERROR", "details": {"error": "unknown operation"},
                    "warnings": [], "duration_s": 0.0}
        return fn(**kwargs)

    @staticmethod
    def operations() -> list[str]:
        return ["integrity", "analyze", "optimize", "checkpoint", "vacuum",
                "vacuum-precheck", "fts-consistency", "fts-rebuild",
                "prune-relations", "prune-intel", "prune-artifacts", "prune-audit",
                "orphan-scan", "semantic-consistency", "schema-init", "status"]
