"""Bounded, read-only file-count estimation for the Scanner progress bar.

The Streamlit Scanner shows an *estimated* progress bar while a long scan runs.
That estimate must never influence the lifecycle (``ScanService`` stays the sole
owner of COMPLETED / CANCELLED / FAILED), must never load files into memory, and
must never mutate the database.  This module only counts directory entries.

Safety properties, mirroring ``FastScannerEngine``:

* symlinks are never followed (neither the root nor any descendant);
* traversal never crosses the root filesystem device (same boundary as the
  scanner, which drops foreign mounts);
* pseudo filesystems (``/proc``, ``/sys``, ``/dev``, tmpfs, image mounts, ...)
  are rejected as roots and skipped as descendants;
* the walk is hard-bounded by wall-clock time, directory count and file count;
* any failure degrades to ``available=False`` instead of raising, so a broken
  estimate can never make the real scan unsafe or fail.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..scanner.fast_engine import FastScannerEngine

#: Kernel-virtual / image filesystem types that never contain user corpus files.
#: ``tmpfs``/``ramfs`` are intentionally *not* listed: they can legitimately
#: hold user data (``/tmp``, ``/run/user``), and the device-boundary check
#: already skips them when they are mounted inside another scan root.
PSEUDO_FS_TYPES = frozenset(
    {
        "proc",
        "procfs",
        "sysfs",
        "devtmpfs",
        "devpts",
        "cgroup",
        "cgroup2",
        "pstore",
        "securityfs",
        "debugfs",
        "tracefs",
        "configfs",
        "fusectl",
        "mqueue",
        "hugetlbfs",
        "binfmt_misc",
        "autofs",
        "rpc_pipefs",
        "nsfs",
        "bpf",
        "efivarfs",
        "squashfs",
        "iso9660",
        "udf",
    }
)

DEFAULT_MAX_SECONDS = 10.0
DEFAULT_MAX_DIRS = 200_000
DEFAULT_MAX_FILES = 5_000_000


@dataclass(frozen=True)
class ScanEstimate:
    """Outcome of a bounded estimation pass.

    ``complete`` is False when a cap (time/dirs/files) was reached, in which
    case ``estimated_files`` is a lower bound.  ``available`` is False when the
    root could not be estimated at all (missing, unreadable, pseudo filesystem).
    """

    root: str
    available: bool
    estimated_files: int = 0
    complete: bool = False
    dirs_visited: int = 0
    elapsed_s: float = 0.0
    reason: str = ""


def _filesystem_device(path: str | Path) -> int | None:
    """Return the device id for *path*, or None when it cannot be read."""
    try:
        return int(Path(path).stat().st_dev)
    except (OSError, ValueError):
        return None


def is_pseudo_filesystem(path: str | Path) -> bool:
    """Return True when *path* lives on a pseudo/image filesystem."""
    try:
        from .volume import resolve_volume

        info = resolve_volume(path)
    except Exception:  # noqa: BLE001 - estimation must never raise
        return False
    fs_type = (info.fs_type or "").lower()
    return fs_type in PSEUDO_FS_TYPES


def estimate_files(
    root: str | Path,
    *,
    cancel_event: threading.Event | None = None,
    stop_event: threading.Event | None = None,
    include_system: bool = False,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_dirs: int = DEFAULT_MAX_DIRS,
    max_files: int = DEFAULT_MAX_FILES,
) -> ScanEstimate:
    """Estimate how many files a scan of *root* will see.

    The walk is intentionally cheap and bounded.  It returns a lower bound when
    a cap is reached and ``available=False`` when no estimate is possible.
    """
    started = time.monotonic()

    def _cancelled() -> bool:
        return bool(
            (cancel_event is not None and cancel_event.is_set())
            or (stop_event is not None and stop_event.is_set())
        )

    try:
        root_path = Path(root).expanduser()
        root_device = _filesystem_device(root_path)
        if root_device is None or not root_path.is_dir():
            return ScanEstimate(
                root=str(root_path),
                available=False,
                reason="root_unreadable",
                elapsed_s=time.monotonic() - started,
            )
        if is_pseudo_filesystem(root_path):
            return ScanEstimate(
                root=str(root_path),
                available=False,
                reason="pseudo_filesystem",
                elapsed_s=time.monotonic() - started,
            )

        # Reuse the scanner's own skip rules so the estimate tracks the real
        # traversal instead of inventing a second policy.
        engine = FastScannerEngine()  # type: ignore[no-untyped-call]
        stack: list[Path] = [root_path]
        dirs_visited = 0
        files_found = 0
        complete = True
        reason = ""

        while stack:
            if _cancelled():
                complete = False
                reason = "cancelled"
                break
            if time.monotonic() - started >= max_seconds:
                complete = False
                reason = "time_budget"
                break
            if dirs_visited >= max_dirs:
                complete = False
                reason = "max_dirs"
                break

            directory = stack.pop()
            dirs_visited += 1
            device = _filesystem_device(directory)
            if device is None or device != root_device:
                # Foreign mount or vanished directory: same boundary as the
                # scanner, which never crosses devices.
                continue
            if directory != root_path and engine._should_skip_directory(directory):
                continue

            try:
                iterator = os.scandir(directory)
            except OSError:
                continue

            try:
                with iterator:
                    for entry in iterator:
                        if _cancelled():
                            complete = False
                            reason = "cancelled"
                            break
                        if files_found >= max_files:
                            complete = False
                            reason = "max_files"
                            break
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                        except OSError:
                            continue

                        candidate = Path(entry.path)
                        try:
                            if engine._should_skip_file_fast(
                                candidate, include_system=include_system
                            ):
                                continue
                        except OSError:
                            continue
                        files_found += 1
            except OSError:
                continue

            if not complete:
                break

        return ScanEstimate(
            root=str(root_path),
            available=True,
            estimated_files=files_found,
            complete=complete,
            dirs_visited=dirs_visited,
            elapsed_s=time.monotonic() - started,
            reason=reason,
        )
    except Exception as exc:  # noqa: BLE001 - an estimate must never be fatal
        return ScanEstimate(
            root=str(root),
            available=False,
            reason=f"{type(exc).__name__}: {exc}",
            elapsed_s=time.monotonic() - started,
        )
