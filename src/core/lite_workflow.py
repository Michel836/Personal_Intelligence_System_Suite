"""Bounded, local Lite jobs, shared by the UI and acceptance tests."""
from __future__ import annotations

import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .database import DatabaseManager
from .scan_service import ScanRequest, ScanService

EXTENSIONS = (".txt", ".md", ".pdf", ".docx", ".xlsx")


def extraction_pipeline(db: DatabaseManager):
    """Reuse canonical persistence/retry policy with only Lite extractors."""
    from ..extractors.manager import ExtractionManager
    from ..extractors.office_extractor import OfficeExtractor
    from ..extractors.pdf_extractor import PDFExtractor
    from ..extractors.text_extractor import TextExtractor
    from ..ingest.pipeline import IngestionPipeline

    # Avoid constructing optional email/OCR/archive tools in the Lite workflow.
    manager = ExtractionManager(extractors=[PDFExtractor(), OfficeExtractor(), TextExtractor()])
    return IngestionPipeline(db, manager=manager)


def validate_root(raw: str) -> Path:
    if not raw.strip():
        raise ValueError("Choisissez un dossier à indexer.")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Le chemin doit désigner un dossier existant.")
    return root


class LiteJob:
    """One job per session; cancellation targets the actual worker.

    Workers never access Streamlit state. A locked snapshot replaces unbounded
    progress queues. A cancelled scan preserves the previous index lifecycle.
    Extraction stops between files; it does not kill an active parser.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {"status": "IDLE"}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _update(self, **values: Any) -> None:
        with self._lock:
            self._state.update(values)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, operation: str, root: str | None = None, *, limit: int = 100) -> None:
        if self.running:
            raise ValueError("Une opération est déjà en cours.")
        if operation not in {"scan", "extract"}:
            raise ValueError("Opération inconnue.")
        if operation == "scan":
            root = str(validate_root(root or ""))
        elif limit < 1 or limit > 1000:
            raise ValueError("Le lot doit contenir entre 1 et 1 000 fichiers.")
        self.cancel_event.clear()
        with self._lock:
            self._state = {"operation": operation, "status": "RUNNING", "processed": 0}
        self._thread = threading.Thread(
            target=self._run, args=(operation, root, limit), name="pis-lite-job", daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def join(self, timeout: float = 30) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self, operation: str, root: str | None, limit: int) -> None:
        try:
            db = DatabaseManager(self.db_path)
            if operation == "scan":
                result = ScanService(db).run(
                    ScanRequest(Path(root), batch_size=250),
                    cancel_event=self.cancel_event,
                    progress_callback=lambda r: self._update(processed=r.files_seen),
                )
                self._update(**asdict(result), processed=result.files_seen)
            else:
                pipeline = extraction_pipeline(db)
                # A directory boundary avoids extracting a similarly named sibling.
                scope = str(validate_root(root)).rstrip(os.sep) + os.sep if root else None
                rows = pipeline.eligible(limit=limit, scope_prefix=scope, extensions=list(EXTENSIONS))
                self._update(total=len(rows))
                counts: dict[str, int] = {}
                for i, row in enumerate(rows):
                    if self.cancel_event.is_set():
                        break
                    outcome = pipeline.extract_file(row["id"], row["path"], extension=row["extension"])
                    counts[outcome] = counts.get(outcome, 0) + 1
                    self._update(processed=i + 1, counts=dict(counts))
                self._update(status="CANCELLED" if self.cancel_event.is_set() else "COMPLETED",
                             counts=dict(counts))
        except Exception as exc:
            self._update(status="FAILED", error=str(exc))
