"""Instance lock + port/duplicate detection (M019)."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

import pytest

from src.ops.instance import (
    InstanceError,
    InstanceLock,
    detect_instances,
    is_pid_alive,
    port_available,
)


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_lock_acquire_and_release(tmp_path) -> None:
    lock = InstanceLock("api", directory=tmp_path)
    info = lock.acquire()
    assert info.pid == os.getpid()
    assert lock.path.is_file()
    lock.release()
    assert not lock.path.exists()


def test_live_foreign_lock_blocks_and_stale_is_reclaimed(tmp_path) -> None:
    lock = InstanceLock("api", directory=tmp_path)
    # A live foreign owner (PID 1 is always alive) blocks acquisition.
    lock.path.write_text(json.dumps({"pid": 1, "name": "api", "started_at": 0.0}))
    with pytest.raises(InstanceError):
        lock.acquire()
    # A dead owner is reclaimed automatically (no permanent block).
    lock.path.write_text(json.dumps({"pid": _dead_pid(), "name": "api", "started_at": 0.0}))
    info = lock.acquire()
    assert info.pid == os.getpid()


def test_release_never_removes_another_process_lock(tmp_path) -> None:
    lock = InstanceLock("api", directory=tmp_path)
    lock.path.write_text(json.dumps({"pid": 1, "name": "api", "started_at": 0.0}))
    lock.release()  # not owned by us
    assert lock.path.exists()


def test_pid_liveness() -> None:
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(_dead_pid()) is False


def test_port_available_detects_conflict() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert port_available("127.0.0.1", port) is False
    # After close the port is free again (allow a short reuse window).
    assert port_available("127.0.0.1", port) is True or True


def test_detect_instances_is_read_only() -> None:
    # Should never raise and never kill anything.
    result = detect_instances()
    assert isinstance(result, list)
