"""Canonical extraction pipeline with outcome taxonomy, retry queue and threads.

Builds on ``ExtractionManager`` (which now includes the email, legacy, EPUB and
CHM extractors). Records every non-success in the persistent queue, applies the
deterministic retry policy, persists conservative email thread relations and
flows extracted text through the existing ``update_content`` path so FTS,
semantic state, language/entities/categories/PII and the graph all see it.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from ..extractors.manager import ExtractionManager
from .queue_store import ExtractionQueue
from .taxonomy import Outcome, classify_error
from .thread_store import EmailThreadStore

_EMAIL_EXTENSIONS = {".eml", ".mht", ".mhtml", ".msg"}
_OCR_EXTENSIONS = {".pdf"}


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


class IngestionPipeline:
    def __init__(self, db: Any, *, manager: ExtractionManager | None = None,
                 queue: ExtractionQueue | None = None,
                 threads: EmailThreadStore | None = None) -> None:
        self.db = db
        self.manager = manager or ExtractionManager(max_workers=1)
        self.queue = queue or ExtractionQueue(db)
        self.threads = threads or EmailThreadStore(db)
        self.supported = self.manager.get_supported_extensions()

    # -- eligibility -------------------------------------------------------
    def eligible(self, *, limit: int | None = None, scope_prefix: str | None = None,
                 min_size: int = 1, max_size: int = 50 * 1024 * 1024,
                 include_terminal: bool = False,
                 extensions: list[str] | None = None) -> list[dict[str, Any]]:
        exts = sorted(set(extensions) & self.supported if extensions else self.supported)
        ph = ",".join("?" * len(exts))
        sql = (f"SELECT f.id, f.path, f.extension, f.size_bytes FROM files f "
               f"WHERE f.document_kind='PHYSICAL_FILE' AND COALESCE(f.state,'ACTIVE')='ACTIVE' "
               f"AND f.content_extracted=0 AND f.size_bytes>=? AND f.size_bytes<=? "
               f"AND f.extension IN ({ph})")
        params: list[Any] = [int(min_size), int(max_size), *exts]
        if scope_prefix:
            sql += " AND f.path LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(scope_prefix))
        if not include_terminal:
            sql += (" AND NOT EXISTS (SELECT 1 FROM extraction_queue q WHERE q.file_id=f.id "
                    "AND q.operation='extract' AND q.terminal=1)")
        sql += " ORDER BY f.size_bytes ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # -- single file -------------------------------------------------------
    def extract_file(self, file_id: int, path: str, *, extension: str | None = None,
                     ocr_explicit: bool = False) -> str:
        fid = int(file_id)
        ext = (extension or Path(path).suffix).lower()
        time.perf_counter()
        try:
            res = self.manager.extract_single(Path(path))
        except Exception as exc:  # noqa: BLE001 - one file must not stop the run
            self.queue.record(fid, Outcome.TRANSIENT_ERROR.value, detail=type(exc).__name__)
            return Outcome.TRANSIENT_ERROR.value
        content = (res.content or "")
        if res.success and content.strip():
            self.db.update_content(fid, content)
            self.queue.clear(fid)
            if ext in _EMAIL_EXTENSIONS and res.metadata:
                import contextlib
                with contextlib.suppress(Exception):
                    self.threads.record(fid, res.metadata)
            return Outcome.EXTRACTED.value
        if res.success:
            outcome = Outcome.NO_TEXT.value
        elif ext in _OCR_EXTENSIONS and "no text" in (res.error or "").lower():
            outcome = Outcome.OCR_REQUIRED.value
        else:
            outcome = classify_error(res.error)
        # OCR policy: image-only PDFs (or explicitly requested) when enabled.
        if outcome == Outcome.OCR_REQUIRED.value:
            from ..extractors.ocr import (
                is_ocr_candidate,
                ocr_enabled,
                ocr_file,
                tesseract_available,
            )
            if is_ocr_candidate(Path(path), pdf_had_text=False, explicit=ocr_explicit):
                if ocr_enabled() and tesseract_available():
                    ocr_res = ocr_file(Path(path))
                    if ocr_res.success and (ocr_res.content or "").strip():
                        self.db.update_content(fid, ocr_res.content)
                        self.queue.clear(fid)
                        return Outcome.EXTRACTED.value
                    outcome = Outcome.OCR_FAILED.value
                else:
                    outcome = Outcome.OCR_REQUIRED.value
        self.db.mark_extraction_attempted(fid)
        self.queue.record(fid, outcome, detail=(res.error or "")[:120])
        return outcome

    # -- batches -----------------------------------------------------------
    def run(self, *, limit: int | None = None, scope_prefix: str | None = None,
            min_size: int = 1, max_size: int = 50 * 1024 * 1024, ocr_explicit: bool = False,
            extensions: list[str] | None = None,
            progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        docs = self.eligible(limit=limit, scope_prefix=scope_prefix,
                             min_size=min_size, max_size=max_size, extensions=extensions)
        return self._run_rows(docs, ocr_explicit=ocr_explicit, progress=progress)

    def run_retries(self, *, limit: int = 200, ocr_explicit: bool = False,
                    progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        rows = self.queue.retryable(limit=limit)
        return self._run_rows(rows, ocr_explicit=ocr_explicit, progress=progress)

    def _run_rows(self, rows: list[dict[str, Any]], *, ocr_explicit: bool,
                  progress: Callable[[int, int], None] | None) -> dict[str, Any]:
        counts: dict[str, int] = {}
        t0 = time.perf_counter()
        for i, r in enumerate(rows):
            outcome = self.extract_file(int(r["id"]), r["path"], extension=r.get("extension"),
                                        ocr_explicit=ocr_explicit)
            counts[outcome] = counts.get(outcome, 0) + 1
            if progress and (i + 1) % 200 == 0:
                progress(i + 1, len(rows))
        wall = time.perf_counter() - t0
        stats = {"attempted": len(rows), "counts": counts, "wall_s": round(wall, 3),
                 "docs_per_sec": round(len(rows) / wall, 1) if wall else 0,
                 "queue": self.queue.stats()}
        logger.info(f"ingestion run: {stats['attempted']} docs, counts={counts}")
        return stats

    def capabilities(self) -> dict[str, Any]:
        from .capabilities import capability_matrix
        return capability_matrix()
