"""Safe scanner runtime used by the canonical Streamlit scanner page.

The UI must never reimplement scan lifecycle rules.  This module delegates every
real scan to :class:`src.core.scan_service.ScanService` so traversal, bounded
memory, cancellation and reconciliation all share the same production path as
the CLI.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from src.core.scan_service import ScanRequest, ScanResult, ScanService

UpdateCallback = Callable[[dict[str, Any]], None]


def run_scan_paths(
    db: Any,
    paths: Iterable[str | Path],
    *,
    cancel_event: threading.Event,
    update: UpdateCallback,
    batch_size: int = 1000,
) -> list[ScanResult]:
    """Scan *paths* sequentially through ``ScanService.run``.

    There is deliberately no file-count limit, post-scan size filter, fake
    thread selector or caller-owned ``complete_scan``.  A selected root is a
    reconciliation scope, therefore a production scan must either traverse that
    scope completely, fail closed, or be cancelled without reconciliation.
    """
    service = ScanService(db)
    results: list[ScanResult] = []

    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if cancel_event.is_set():
            break

        started = time.monotonic()
        last_seen = 0

        update(
            {
                "status": "running",
                "path": str(path),
                "files_seen": 0,
                "files_upserted": 0,
                "files_errors": 0,
                "elapsed_s": 0.0,
                "files_per_second": 0.0,
                "message": "Scan started",
            }
        )

        def on_progress(result: ScanResult) -> None:
            nonlocal last_seen
            last_seen = result.files_seen
            elapsed = max(time.monotonic() - started, 1e-9)
            update(
                {
                    "status": "running",
                    "path": result.root_path,
                    "run_id": result.run_id,
                    "files_seen": result.files_seen,
                    "files_upserted": result.files_upserted,
                    "files_errors": result.files_errors,
                    "elapsed_s": elapsed,
                    "files_per_second": result.files_seen / elapsed,
                    "message": "Scanning",
                }
            )

        result = service.run(
            ScanRequest(root=path, limit=None, batch_size=batch_size),
            cancel_event=cancel_event,
            progress_callback=on_progress,
        )
        results.append(result)

        elapsed = max(time.monotonic() - started, 1e-9)
        update(
            {
                "status": result.status.lower(),
                "path": result.root_path,
                "run_id": result.run_id,
                "files_seen": result.files_seen,
                "files_upserted": result.files_upserted,
                "files_errors": result.files_errors,
                "renamed": result.renamed,
                "missing": result.missing,
                "elapsed_s": elapsed,
                "files_per_second": result.files_seen / elapsed,
                "error": result.error,
                "message": result.error or result.status,
            }
        )

        if result.status != "COMPLETED":
            break

    return results
