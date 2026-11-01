"""Canonical scan orchestration shared by scripts and the Streamlit UI.

One state machine, one persistence contract:

    begin_scan -> scan -> record_scan_files (batched) -> complete_scan
                  |                                     (reconcile)
                  +-- cancel_event -> cancel_scan
                  +-- exception    -> fail_scan
                  +-- bounded run  -> cancel_scan (never reconcile)

``ScanService.run`` drives a scanner end-to-end; ``ScanSession`` exposes the
same lifecycle for callers that already own their scan loop.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

from loguru import logger

from ..scanner.fast_engine import FastScannerEngine
from ..scanner.models import FileInfo
from .database import DatabaseManager
from .perf_config import get_resource_config
from .volume import VolumeInfo


_SCAN_SENTINEL = object()


@dataclass
class ScanRequest:
    """Inputs for a single scan run.

    ``limit`` is a diagnostic/bounded traversal only.  Because an unseen path in
    a bounded traversal cannot be interpreted as deleted, any request with a
    limit is persisted without reconciliation and ends as ``CANCELLED``.

    ``ignore_errors`` enables a *safe partial* scan: unreadable subtrees and
    files are recorded per path, the scan ends ``COMPLETED_WITH_WARNINGS``, and
    reconciliation only runs over the portions that were fully traversed.
    ``exclude_dirs`` accepts basename globs (``node_modules``, ``*.tmp``) or
    path patterns; ``exclude_paths`` accepts absolute paths whose subtrees are
    never traversed and never reconciled.
    """

    root: Path
    limit: Optional[int] = None
    include_system: bool = False
    batch_size: int = 1000
    volume: Optional[VolumeInfo] = None
    ignore_errors: bool = False
    exclude_dirs: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()


@dataclass
class ScanResult:
    """Outcome of a scan run.

    ``status`` is COMPLETED, COMPLETED_WITH_WARNINGS, FAILED or CANCELLED.
    """

    run_id: int
    root_path: str
    volume_id: int
    status: str
    files_seen: int = 0
    files_upserted: int = 0
    files_errors: int = 0
    renamed: int = 0
    missing: int = 0
    error: Optional[str] = None
    #: Paths (errors or exclusions) that were not exhaustively traversed.
    unscanned_scopes: int = 0
    #: False when reconciliation was skipped (too many scopes / bounded run).
    reconciled: bool = False
    #: Human-readable warning lines suitable for the CLI/UI.
    warnings: list[str] = field(default_factory=list)


class ScanSession:
    """Lifecycle context for a caller-owned scan loop."""

    def __init__(self, db: DatabaseManager, root: Path, volume: Optional[VolumeInfo] = None):
        self.db = db
        self._info = db.begin_scan(root, volume=volume)
        self.run_id = int(self._info["run_id"])
        self.volume_id = int(self._info["volume_id"])
        self.root_path = self._info["root_path"]
        self.files_seen = 0
        self.files_upserted = 0
        self._finished = False

    def record(self, files: list[FileInfo]) -> int:
        if not files:
            return 0
        upserted = self.db.record_scan_files(self.run_id, files)
        self.files_seen += len(files)
        self.files_upserted += upserted
        return upserted

    def complete(self) -> dict:
        result = self.db.complete_scan(self.run_id)
        self._finished = True
        return result

    def cancel(self) -> None:
        self.db.cancel_scan(self.run_id)
        self._finished = True

    def fail(self, error_message: Optional[str] = None) -> None:
        self.db.fail_scan(self.run_id, error_message)
        self._finished = True

    def __enter__(self) -> "ScanSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._finished:
            self.fail(str(exc) if exc else "scan aborted before completion")
        return False


class ScanService:
    """Drive scanner engines through the canonical lifecycle."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def session(self, root, *, volume: Optional[VolumeInfo] = None) -> ScanSession:
        return ScanSession(self.db, Path(root), volume=volume)

    def _set_run_error_count(self, run_id: int, count: int) -> None:
        """Persist scanner error telemetry without changing lifecycle state."""
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE scan_runs SET files_errors = ? WHERE id = ?",
                (int(count), int(run_id)),
            )
            conn.commit()

    def _iter_files(
        self,
        scanner,
        request: ScanRequest,
        cancel_event: Optional[threading.Event],
        overlap: bool = True,
    ) -> Iterator[FileInfo]:
        """Yield scanned files while keeping memory bounded.

        Producer exceptions are transported to the consumer and re-raised. A
        failed traversal must never be mistaken for a clean end-of-stream.
        """
        stream = scanner.scan_paths(
            [request.root],
            limit=request.limit,
            include_system=request.include_system,
            ignore_errors=request.ignore_errors,
            exclude_dirs=request.exclude_dirs,
            exclude_paths=request.exclude_paths,
        )
        if not overlap:
            for file_info in stream:
                if cancel_event is not None and cancel_event.is_set():
                    return
                yield file_info
            return

        work: "queue.Queue[object]" = queue.Queue(maxsize=512)
        stop = threading.Event()

        def put_control(item: object) -> None:
            while True:
                try:
                    work.put(item, timeout=0.2)
                    return
                except queue.Full:
                    if stop.is_set():
                        return

        def produce() -> None:
            try:
                for file_info in stream:
                    if stop.is_set():
                        break
                    put_control(file_info)
            except BaseException as exc:
                put_control(exc)
            finally:
                put_control(_SCAN_SENTINEL)

        producer = threading.Thread(target=produce, name="pis-scan-producer", daemon=True)
        producer.start()
        try:
            while True:
                item = work.get()
                if item is _SCAN_SENTINEL:
                    break
                if isinstance(item, BaseException):
                    raise item
                if cancel_event is not None and cancel_event.is_set():
                    stop.set()
                    continue
                assert isinstance(item, FileInfo)
                yield item
        finally:
            stop.set()
            try:
                while True:
                    work.get_nowait()
            except queue.Empty:
                pass
            producer.join(timeout=5)

    def run(
        self,
        request: ScanRequest,
        *,
        cancel_event: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[ScanResult], None]] = None,
    ) -> ScanResult:
        """Scan a single root through the lifecycle and return the outcome.

        Reconciliation is fail-closed.  Access errors, explicit cancellation and
        deliberately bounded scans preserve existing ACTIVE rows and never infer
        deletion from paths that were not exhaustively traversed.
        """
        scanner = FastScannerEngine()
        try:
            info = self.db.begin_scan(request.root, volume=request.volume)
        except Exception as exc:
            logger.error(f"could not start scan for {request.root}: {exc}")
            return ScanResult(
                run_id=-1,
                root_path=str(request.root),
                volume_id=-1,
                status="FAILED",
                error=str(exc),
            )

        effective_request = ScanRequest(
            root=Path(info["root_path"]),
            limit=request.limit,
            include_system=request.include_system,
            batch_size=request.batch_size,
            volume=request.volume,
            ignore_errors=request.ignore_errors,
            exclude_dirs=request.exclude_dirs,
            exclude_paths=request.exclude_paths,
        )
        result = ScanResult(
            run_id=int(info["run_id"]),
            root_path=info["root_path"],
            volume_id=int(info["volume_id"]),
            status="RUNNING",
        )
        batch: list[FileInfo] = []
        bulk = get_resource_config().bulk_index
        overlap = get_resource_config().scan_overlap

        try:
            with self.db.bulk_indexing(bulk):
                for file_info in self._iter_files(
                    scanner, effective_request, cancel_event, overlap
                ):
                    batch.append(file_info)
                    if len(batch) >= effective_request.batch_size:
                        result.files_upserted += self.db.record_scan_files(
                            result.run_id, batch
                        )
                        result.files_seen += len(batch)
                        batch = []
                        if progress_callback:
                            progress_callback(result)

                if cancel_event is not None and cancel_event.is_set():
                    if batch:
                        result.files_upserted += self.db.record_scan_files(
                            result.run_id, batch
                        )
                        result.files_seen += len(batch)
                    result.files_errors = self._persist_scopes(scanner, result)
                    self._set_run_error_count(result.run_id, result.files_errors)
                    self.db.cancel_scan(result.run_id)
                    result.status = "CANCELLED"
                    result.error = "scan cancelled; reconciliation skipped"
                    result.warnings.append(result.error)
                    if progress_callback:
                        progress_callback(result)
                    return result

                if batch:
                    result.files_upserted += self.db.record_scan_files(result.run_id, batch)
                    result.files_seen += len(batch)
                    if progress_callback:
                        progress_callback(result)

            result.files_errors = self._persist_scopes(scanner, result)
            self._set_run_error_count(result.run_id, result.files_errors)
            if getattr(scanner, "traversal_incomplete", False):
                raise RuntimeError(
                    "scan incomplete: too many filesystem errors to reconcile safely"
                )
            if result.files_errors and not effective_request.ignore_errors:
                raise RuntimeError(
                    f"scan incomplete: {result.files_errors} filesystem access errors"
                )

            if effective_request.limit is not None:
                self.db.cancel_scan(result.run_id)
                result.status = "CANCELLED"
                result.error = (
                    "bounded scan completed without reconciliation; "
                    "unseen paths were preserved"
                )
                result.warnings.append(result.error)
                if progress_callback:
                    progress_callback(result)
                return result

            rec = self.db.complete_scan(result.run_id)
            result.status = str(rec.get("status") or "COMPLETED")
            result.renamed = int(rec["renamed"])
            result.missing = int(rec["missing"])
            result.reconciled = bool(rec.get("reconciled", True))
            result.unscanned_scopes = int(rec.get("scopes", 0))
            if result.status == "COMPLETED_WITH_WARNINGS":
                result.warnings.append(
                    f"{result.unscanned_scopes} unreadable/excluded scope(s) were "
                    "not reconciled"
                )
            if not result.reconciled:
                result.warnings.append(
                    "reconciliation skipped: too many unscanned scopes"
                )
            if progress_callback:
                progress_callback(result)
            return result

        except Exception as exc:
            result.files_errors = max(
                result.files_errors,
                self._persist_scopes(scanner, result),
            )
            try:
                self._set_run_error_count(result.run_id, result.files_errors)
            except Exception:
                pass
            # One actionable line at WARNING; the traceback is DEBUG only.
            logger.warning(f"scan failed for {effective_request.root}: {exc}")
            logger.debug("scan failure details", exc_info=exc)
            try:
                self.db.fail_scan(result.run_id, str(exc))
            except Exception as fail_exc:
                logger.error(f"could not mark scan FAILED: {fail_exc}")
            result.status = "FAILED"
            result.error = str(exc)
            if progress_callback:
                progress_callback(result)
            return result

    def _persist_scopes(self, scanner, result: ScanResult) -> int:
        """Persist the scanner's per-path errors/exclusions; return error count."""
        scopes = list(getattr(getattr(scanner, "progress", None), "errors", []) or [])
        try:
            self.db.record_scan_scopes(result.run_id, scopes)
        except Exception as exc:  # noqa: BLE001 - telemetry must not mask the scan
            logger.warning(f"could not persist scan scopes: {exc}")
        return int(getattr(scanner.progress, "error_files", 0) or 0)

    def run_turbo(
        self,
        root,
        *,
        volume: Optional[VolumeInfo] = None,
        progress_callback: Optional[Callable[[ScanResult], None]] = None,
    ) -> ScanResult:
        """Run TurboScanner under the same lifecycle contract."""
        from ..scanner.turbo_scan import TurboScanner

        try:
            info = self.db.begin_scan(root, volume=volume)
        except Exception as exc:
            logger.error(f"could not start turbo scan for {root}: {exc}")
            return ScanResult(
                run_id=-1,
                root_path=str(root),
                volume_id=-1,
                status="FAILED",
                error=str(exc),
            )
        result = ScanResult(
            run_id=int(info["run_id"]),
            root_path=info["root_path"],
            volume_id=int(info["volume_id"]),
            status="RUNNING",
        )
        turbo = TurboScanner(db=self.db)
        turbo.set_scan_context(result.volume_id, result.run_id)
        try:
            with self.db.bulk_indexing(get_resource_config().bulk_index):
                stats = turbo.turbo_scan(Path(info["root_path"]))
            if stats is None:
                self.db.cancel_scan(result.run_id)
                result.status = "CANCELLED"
                return result
            result.files_seen = int(stats.get("files_found", 0))
            result.files_upserted = int(stats.get("files_processed", 0))
            result.files_errors = int(stats.get("files_errors", 0))
            self._set_run_error_count(result.run_id, result.files_errors)
            if result.files_errors:
                raise RuntimeError(
                    f"turbo scan incomplete: {result.files_errors} filesystem errors"
                )
            rec = self.db.complete_scan(result.run_id)
            result.status = "COMPLETED"
            result.renamed = int(rec["renamed"])
            result.missing = int(rec["missing"])
            if progress_callback:
                progress_callback(result)
            return result
        except Exception as exc:
            logger.exception(f"turbo scan failed for {root}: {exc}")
            try:
                self.db.fail_scan(result.run_id, str(exc))
            except Exception:
                pass
            result.status = "FAILED"
            result.error = str(exc)
            return result
