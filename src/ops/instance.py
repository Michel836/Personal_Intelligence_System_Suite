"""Process / instance safety (M019, phase 19).

The application previously allowed many orphaned Streamlit processes to pile up.
This module provides:

* a PID-based :class:`InstanceLock` with **stale-lock recovery** (a crashed
  owner does not block forever);
* read-only duplicate detection (it never kills another process);
* port-conflict detection.

The lock is advisory and stored under ``PIS_LOCK_DIR`` (default
``~/.pis-locks``); it is never written inside a scanned source tree.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_LOCK_DIR = Path.home() / ".pis-locks"


class InstanceError(RuntimeError):
    """Raised when a live instance already owns the lock."""


def lock_dir() -> Path:
    return Path(os.environ.get("PIS_LOCK_DIR") or DEFAULT_LOCK_DIR).expanduser()


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


@dataclass
class LockInfo:
    pid: int
    name: str
    started_at: float
    port: int | None = None
    cmdline: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "name": self.name, "started_at": self.started_at,
                "port": self.port, "cmdline": self.cmdline}


class InstanceLock:
    def __init__(self, name: str, *, directory: Path | None = None,
                 port: int | None = None) -> None:
        self.name = name
        self.directory = directory or lock_dir()
        self.port = port
        self.path = self.directory / f"{name}.lock"
        self._owned = False

    def read(self) -> LockInfo | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            return LockInfo(pid=int(data["pid"]), name=str(data.get("name", self.name)),
                            started_at=float(data.get("started_at", 0)),
                            port=data.get("port"), cmdline=data.get("cmdline"))
        except (KeyError, TypeError, ValueError):
            return None

    def _write(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"pid": os.getpid(), "name": self.name, "started_at": time.time(),
                   "port": self.port, "cmdline": " ".join(sys.argv)[:300]}
        tmp = self.path.with_name(self.path.name + f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)

    def acquire(self, *, force: bool = False) -> LockInfo:
        """Acquire the lock or raise. Reclaims a stale lock automatically."""
        existing = self.read()
        if (not force and existing is not None and existing.pid != os.getpid()
                and is_pid_alive(existing.pid)):
            raise InstanceError(
                f"instance '{self.name}' already running (pid={existing.pid})")
        self._write()
        self._owned = True
        return self.read() or LockInfo(os.getpid(), self.name, time.time(), self.port)

    def release(self) -> None:
        if not self._owned:
            return
        current = self.read()
        if current is not None and current.pid != os.getpid():
            return  # never remove another process's lock
        import contextlib
        with contextlib.suppress(OSError):
            self.path.unlink(missing_ok=True)
        self._owned = False

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def detect_instances(needle: str = "src/ui/app.py") -> list[dict[str, Any]]:
    """Return existing app processes (read-only; never kills anything)."""
    found: list[dict[str, Any]] = []
    try:
        import psutil  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001
        return found
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
        except Exception:  # noqa: BLE001
            continue
        if needle in cmdline and "streamlit" in cmdline:
            port = None
            parts = cmdline.split()
            if "--server.port" in parts:
                idx = parts.index("--server.port")
                if idx + 1 < len(parts) and parts[idx + 1].isdigit():
                    port = int(parts[idx + 1])
            found.append({"pid": proc.info["pid"], "port": port,
                          "started_at": proc.info.get("create_time")})
    return found
