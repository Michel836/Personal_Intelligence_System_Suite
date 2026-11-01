"""Resumable background embedding job + semantic coverage.

Semantic coverage is ``embedded / eligible`` where *eligible* means an ACTIVE
document with extracted content long enough to embed. The job only processes
dirty rows, so it is naturally resumable and idempotent: stopping (or a crash)
leaves rows dirty for the next run.

The canonical CLI wraps this module:

    pis embed --background      # detached worker
    pis embed                   # foreground
    pis embed --status          # progress + coverage
    pis embed --stop            # request a clean stop
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from ..core.coverage import semantic_coverage
from ..core.paths import logs_dir, repo_root, state_dir

STATE_FILE = "embedding_job.json"
STOP_FILE = "embedding_job.stop"
LOG_FILE = "embedding_job.log"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class JobState:
    status: str = "IDLE"  # IDLE|RUNNING|STOPPING|STOPPED|DONE|ERROR|NOT_CONFIGURED
    pid: int | None = None
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    embedded: int = 0
    target: int | None = None
    batch_size: int = 256
    error: str | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    stop_requested: bool = False
    db: str | None = None


class EmbeddingJob:
    """Filesystem-brokered job state (works across processes and the UI)."""

    def __init__(self, db: Any, *, state_path: Path | None = None,
                 stop_path: Path | None = None, log_path: Path | None = None) -> None:
        self.db = db
        base = state_dir()
        self.state_path = Path(state_path) if state_path else base / STATE_FILE
        self.stop_path = Path(stop_path) if stop_path else base / STOP_FILE
        self.log_path = Path(log_path) if log_path else logs_dir() / LOG_FILE

    # -- state ------------------------------------------------------------
    def _ensure_parents(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> JobState:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return JobState()
        known = set(JobState.__dataclass_fields__)
        return JobState(**{k: v for k, v in payload.items() if k in known})

    def _write(self, state: JobState) -> JobState:
        self._ensure_parents()
        state.updated_at = _now()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)
        return state

    def status(self, *, live: bool = True) -> dict[str, Any]:
        state = self.read()
        payload = asdict(state)
        payload["coverage"] = semantic_coverage(self.db) if live else state.coverage
        payload["running"] = self._is_running(state)
        payload["log"] = str(self.log_path) if self.log_path.exists() else None
        payload["stop_requested"] = self.stop_path.exists()
        return payload

    def _is_running(self, state: JobState) -> bool:
        if state.status not in {"RUNNING", "STOPPING"} or not state.pid:
            return False
        try:
            os.kill(int(state.pid), 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def request_stop(self) -> dict[str, Any]:
        self._ensure_parents()
        self.stop_path.write_text(_now(), encoding="utf-8")
        state = self.read()
        if state.status == "RUNNING":
            state.status = "STOPPING"
            state.stop_requested = True
            self._write(state)
        return {"stop_requested": True, "state": asdict(self.read())}

    def clear_stop(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.stop_path.unlink()

    # -- execution ---------------------------------------------------------
    def run(self, *, limit: int | None = None, batch_size: int = 256,
            should_stop: Callable[[], bool] | None = None,
            progress: Callable[[JobState], None] | None = None) -> JobState:
        from .semantic_search import SemanticSearchEngine

        self.clear_stop()
        coverage = semantic_coverage(self.db)
        target = int(limit) if limit else coverage["pending"]
        state = JobState(
            status="RUNNING", pid=os.getpid(), started_at=_now(),
            target=target, batch_size=int(batch_size), coverage=coverage,
            db=str(getattr(self.db, "db_path", "")),
        )
        self._write(state)

        def _stop() -> bool:
            if self.stop_path.exists():
                return True
            return bool(should_stop and should_stop())

        try:
            engine = SemanticSearchEngine(self.db)
            if not engine.is_available():
                state.status = "NOT_CONFIGURED"
                state.error = (
                    "no embedding backend available; install the 'ai' extra "
                    "(pip install -e '.[ai]') or configure PIS_AI_MODE/PIS_API_*"
                )
                state.finished_at = _now()
                state.coverage = semantic_coverage(self.db)
                return self._write(state)

            remaining = target
            while remaining > 0:
                if _stop():
                    state.status = "STOPPED"
                    break
                result = engine.refresh(
                    batch_size=int(batch_size),
                    max_docs=min(int(batch_size), remaining),
                    should_stop=_stop,
                )
                embedded = int(result.get("embedded") or 0)
                pruned = int(result.get("pruned") or 0)
                state.embedded += embedded
                remaining -= max(embedded, 1)  # never spin on a stuck batch
                state.coverage = semantic_coverage(self.db)
                self._write(state)
                if progress is not None:
                    with contextlib.suppress(Exception):  # best-effort callback
                        progress(state)
                if embedded == 0 and pruned == 0:
                    break

            if state.status not in {"STOPPED", "ERROR"}:
                state.status = "DONE"
            state.coverage = semantic_coverage(self.db)
            state.finished_at = _now()
            return self._write(state)
        except Exception as exc:  # noqa: BLE001 - persist the failure for the UI
            logger.warning(f"embedding job failed: {exc}")
            state.status = "ERROR"
            state.error = f"{type(exc).__name__}: {exc}"
            state.coverage = semantic_coverage(self.db)
            state.finished_at = _now()
            return self._write(state)

    # -- background process ------------------------------------------------
    def start_background(self, *, limit: int | None = None,
                         batch_size: int = 256) -> dict[str, Any]:
        running = self.read()
        if self._is_running(running):
            return {"started": False, "reason": "already running",
                    "pid": running.pid, "state": asdict(running)}
        self.clear_stop()
        self._ensure_parents()
        command = [
            sys.executable, "-m", "src.cli", "embed", "--worker",
            "--batch-size", str(int(batch_size)),
        ]
        if limit:
            command += ["--limit", str(int(limit))]
        env = dict(os.environ)
        db_path = str(getattr(self.db, "db_path", "") or "")
        if db_path:
            env["PIS_DB_PATH"] = db_path
        log_handle = open(self.log_path, "ab", buffering=0)  # noqa: SIM115
        try:
            process = subprocess.Popen(
                command, cwd=str(repo_root()), env=env,
                stdout=log_handle, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
            )
        finally:
            log_handle.close()
        # Give the child a moment to fail fast (missing model, bad DB, ...).
        time.sleep(0.3)
        if process.poll() not in (None, 0):
            tail = ""
            with contextlib.suppress(OSError):
                tail = self.log_path.read_text(encoding="utf-8", errors="ignore")[-800:]
            return {"started": False, "reason": "worker exited immediately",
                    "exit_code": process.returncode, "log_tail": tail}
        return {"started": True, "pid": process.pid, "log": str(self.log_path)}
