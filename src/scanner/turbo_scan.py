"""Robust high-throughput metadata scanner for massive local volumes."""

from __future__ import annotations

import os
import stat
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from loguru import logger

from src.core.database import DatabaseManager
from .models import FileInfo, FileType, stat_created_at


class TurboScanner:
    """High-throughput scanner sharing the canonical lifecycle contract.

    Turbo mode intentionally favours deterministic bounded batching over the old
    producer/saver thread pair.  The previous implementation could swallow a
    saver failure and deadlock the producer.  This implementation keeps memory
    bounded, honours filesystem boundaries and reports traversal errors so the
    caller can refuse destructive reconciliation.
    """

    def __init__(self, db: Optional[DatabaseManager] = None):
        # Do not instantiate the default production DB merely by constructing a
        # scanner in tests or tooling.  It is created lazily only if persistence
        # is actually requested without an injected manager.
        self.db = db
        self.volume_id = None
        self.scan_id = None
        self.stats = self._new_stats()

    @staticmethod
    def _new_stats() -> dict:
        return {
            "files_found": 0,
            "files_saved": 0,
            "files_processed": 0,
            "files_errors": 0,
            "total_size": 0,
            "start_time": time.time(),
        }

    def set_scan_context(self, volume_id, scan_id):
        self.volume_id = volume_id
        self.scan_id = scan_id

    @staticmethod
    def _default_excludes() -> set[str]:
        return {
            "System Volume Information", "$Recycle.Bin", "Windows",
            "Program Files", "Program Files (x86)", "ProgramData",
            ".git", "__pycache__", "node_modules", ".vscode", ".vs",
            "Temp", "tmp", "AppData", "Recovery", ".venv", "venv",
            ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
        }

    def _iter_metadata(
        self,
        root_path: Path,
        exclude_dirs: Optional[set[str]] = None,
    ) -> Iterator[FileInfo]:
        """Yield regular files from exactly one filesystem.

        Directory/read/stat errors are counted.  The lifecycle caller must not
        reconcile a run when ``files_errors`` is non-zero.
        """
        excludes = exclude_dirs or self._default_excludes()
        root_path = Path(root_path)
        try:
            root_dev = int(root_path.stat().st_dev)
        except OSError as exc:
            self.stats["files_errors"] += 1
            raise OSError(f"cannot stat turbo scan root {root_path}: {exc}") from exc

        stack = [root_path]
        while stack:
            current = stack.pop()
            try:
                current_stat = current.stat()
            except OSError as exc:
                self.stats["files_errors"] += 1
                logger.warning(f"Turbo cannot stat directory {current}: {exc}")
                continue

            if int(current_stat.st_dev) != root_dev:
                continue

            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name in excludes or entry.name.startswith("."):
                                    continue
                                try:
                                    child_stat = entry.stat(follow_symlinks=False)
                                except OSError as exc:
                                    self.stats["files_errors"] += 1
                                    logger.warning(f"Turbo cannot stat {entry.path}: {exc}")
                                    continue
                                if int(child_stat.st_dev) == root_dev:
                                    stack.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue

                            stat_info = entry.stat(follow_symlinks=False)
                            if int(stat_info.st_dev) != root_dev:
                                continue
                            if not stat.S_ISREG(stat_info.st_mode):
                                continue

                            ext = Path(entry.name).suffix.lower()
                            info = FileInfo(
                                path=Path(entry.path),
                                filename=entry.name,
                                extension=ext,
                                size_bytes=stat_info.st_size,
                                created_at=stat_created_at(stat_info),
                                modified_at=datetime.fromtimestamp(stat_info.st_mtime),
                                device_id=stat_info.st_dev,
                                inode=stat_info.st_ino,
                                file_type=FileType(self.get_file_type(ext)),
                            )
                            self.stats["files_found"] += 1
                            self.stats["total_size"] += stat_info.st_size
                            yield info
                        except (OSError, PermissionError) as exc:
                            self.stats["files_errors"] += 1
                            logger.warning(f"Turbo cannot access {entry.path}: {exc}")
            except (OSError, PermissionError) as exc:
                self.stats["files_errors"] += 1
                logger.warning(f"Turbo cannot scan directory {current}: {exc}")

    def fast_directory_walk(self, root_path, file_queue, exclude_dirs=None):
        """Compatibility adapter: enqueue metadata dictionaries."""
        for info in self._iter_metadata(Path(root_path), exclude_dirs):
            file_queue.put(
                {
                    "path": str(info.path),
                    "filename": info.filename,
                    "size_bytes": info.size_bytes,
                    "modified_at": info.modified_at,
                    "created_at": info.created_at,
                    "device_id": info.device_id,
                    "inode": info.inode,
                }
            )

    def save_batch(self, files: list[FileInfo]) -> int:
        """Persist one batch and return the number processed/upserted."""
        if not files:
            return 0
        if self.db is None:
            self.db = DatabaseManager()

        if self.scan_id is not None:
            # Canonical path: updates both file rows and scan_runs counters.
            written = self.db.record_scan_files(int(self.scan_id), files)
        else:
            written = self.db.save_files_batch(
                files, volume_id=self.volume_id, scan_id=self.scan_id
            )

        self.stats["files_saved"] += int(written)
        self.stats["files_processed"] += len(files)
        return int(written)

    def batch_saver(self, file_queue, batch_size=5000):
        """Compatibility consumer used by older callers."""
        batch: list[FileInfo] = []
        while True:
            entry = file_queue.get()
            try:
                if entry is None:
                    if batch:
                        self.save_batch(batch)
                    return
                ext = Path(entry["filename"]).suffix.lower()
                batch.append(
                    FileInfo(
                        path=Path(entry["path"]),
                        filename=entry["filename"],
                        extension=ext,
                        size_bytes=entry["size_bytes"],
                        created_at=entry["created_at"],
                        modified_at=entry["modified_at"],
                        device_id=entry.get("device_id"),
                        inode=entry.get("inode"),
                        file_type=FileType(self.get_file_type(ext)),
                    )
                )
                if len(batch) >= batch_size:
                    self.save_batch(batch)
                    batch = []
            finally:
                file_queue.task_done()

    def get_file_type(self, extension):
        ext = extension.lower()
        if ext in {'.pdf', '.doc', '.docx', '.rtf', '.txt', '.odt', '.xls', '.xlsx', '.csv', '.ppt', '.pptx'}:
            return 'document'
        if ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.tiff', '.webp'}:
            return 'image'
        if ext in {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'}:
            return 'video'
        if ext in {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma'}:
            return 'audio'
        if ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
            return 'archive'
        if ext in {'.py', '.js', '.html', '.css', '.cpp', '.java', '.cs'}:
            return 'code'
        return 'other'

    def turbo_scan(self, scan_path, batch_size: int = 5000):
        """Run a bounded-memory turbo scan.

        Errors are reported in the returned stats instead of being converted to
        a false success.  ``ScanService.run_turbo`` refuses reconciliation when
        that count is non-zero.
        """
        self.stats = self._new_stats()
        scan_path = Path(scan_path)
        scan_start = time.time()
        batch: list[FileInfo] = []

        logger.info(f"Turbo scan starting: {scan_path}")
        try:
            for info in self._iter_metadata(scan_path):
                batch.append(info)
                if len(batch) >= batch_size:
                    self.save_batch(batch)
                    batch = []
            if batch:
                self.save_batch(batch)
        except KeyboardInterrupt:
            return None
        except Exception:
            logger.exception(f"Turbo scan failed: {scan_path}")
            raise

        duration = time.time() - scan_start
        return {
            "files_found": int(self.stats["files_found"]),
            "files_saved": int(self.stats["files_saved"]),
            "files_processed": int(self.stats["files_processed"]),
            "files_errors": int(self.stats["files_errors"]),
            "total_size_bytes": int(self.stats["total_size"]),
            "total_size_gb": self.stats["total_size"] / (1024 ** 3),
            "duration": duration,
            "files_per_second": self.stats["files_found"] / max(duration, 0.001),
        }


if __name__ == "__main__":
    raise SystemExit(
        "Use the canonical application/CLI scan lifecycle instead of running "
        "TurboScanner as a standalone production entry point."
    )
