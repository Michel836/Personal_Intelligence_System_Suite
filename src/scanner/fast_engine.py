"""Optimized fast scanner engine."""

from pathlib import Path
from typing import Iterator, Optional, Callable, Sequence
from datetime import datetime
import fnmatch
import os
import stat

from loguru import logger
from .models import (
    FileInfo,
    FileType,
    Priority,
    ScanProgress,
    METADATA_INDEX_LIMIT,
    stat_created_at,
)


#: Maximum number of per-path error records kept in memory/DB per scan. The
#: authoritative counter stays ``ScanProgress.error_files``; once the cap is hit
#: the traversal is marked incomplete and reconciliation is disabled entirely
#: (safest possible behaviour).
MAX_RECORDED_ERRORS = 500


class FastScannerEngine:
    """High-speed file scanner optimized for performance.

    Safety invariant: a scan must never look complete when traversal was only
    partial. Directory traversal errors and unexpected scanner exceptions are
    therefore surfaced to the caller so the lifecycle layer can mark the run
    FAILED and avoid destructive reconciliation.
    """

    def __init__(
        self,
        *,
        exclude_dirs: Sequence[str] = (),
        exclude_paths: Sequence[str] = (),
        ignore_errors: bool = False,
    ):
        self.progress = ScanProgress()
        self.is_running = False
        self._cancelled = False
        self._ignore_errors = bool(ignore_errors)
        self._traversal_incomplete = False
        self._scan_root: Optional[Path] = None
        self._exclude_dir_patterns = tuple(
            str(item).strip().lower() for item in exclude_dirs if str(item).strip()
        )
        self._exclude_paths = tuple(
            Path(item).expanduser() for item in exclude_paths if str(item).strip()
        )

        self._priority_extensions = {
            Priority.CRITICAL: {
                '.pdf', '.doc', '.docx', '.xlsx', '.xls',
                '.ppt', '.pptx', '.rtf', '.txt', '.odt',
                '.pst', '.ost', '.msg', '.eml'
            },
            Priority.HIGH: {
                '.jpg', '.jpeg', '.png', '.tiff', '.bmp',
                '.mp4', '.avi', '.mov', '.wmv', '.zip', '.rar'
            }
        }

        self._skip_extensions = {
            '.dll', '.sys', '.exe', '.msi', '.tmp', '.log',
            '.cache', '.lock', '.pid', '.swp', '.~', '.lnk',
            '.bak', '.temp'
        }

        self._skip_dirs = {
            'windows', 'program files', 'program files (x86)',
            'programdata', '$recycle.bin', 'system volume information',
            'windows.old', 'recovery',
            '.git', '.hg', '.svn',
            '.venv', 'venv', 'env',
            'node_modules',
            '__pycache__',
            '.pytest_cache', '.mypy_cache', '.ruff_cache',
            '.tox', '.nox',
            'dist', 'build',
            'coverage', '.coverage',
            '.cache',
        }

    def fast_scan(
        self,
        path: Path,
        limit: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        include_system: bool = False,
        *,
        ignore_errors: Optional[bool] = None,
        exclude_dirs: Optional[Sequence[str]] = None,
        exclude_paths: Optional[Sequence[str]] = None,
    ) -> Iterator[FileInfo]:
        """Ultra-fast single-pass scan."""
        self._reset_cancel()
        self._configure(
            ignore_errors=ignore_errors,
            exclude_dirs=exclude_dirs,
            exclude_paths=exclude_paths,
        )
        yield from self._fast_scan(
            path,
            limit=limit,
            progress_callback=progress_callback,
            include_system=include_system,
        )

    def _configure(
        self,
        *,
        ignore_errors: Optional[bool] = None,
        exclude_dirs: Optional[Sequence[str]] = None,
        exclude_paths: Optional[Sequence[str]] = None,
    ) -> None:
        if ignore_errors is not None:
            self._ignore_errors = bool(ignore_errors)
        if exclude_dirs is not None:
            self._exclude_dir_patterns = tuple(
                str(item).strip().lower() for item in exclude_dirs if str(item).strip()
            )
        if exclude_paths is not None:
            self._exclude_paths = tuple(
                Path(item).expanduser() for item in exclude_paths if str(item).strip()
            )

    @property
    def traversal_incomplete(self) -> bool:
        """True when more errors occurred than could be recorded."""
        return self._traversal_incomplete

    def _record_error(
        self, path: object, kind: str, message: object, *, counts_as_error: bool = True
    ) -> None:
        """Record one access error/excluded scope (bounded).

        ``kind="excluded"`` records a subtree that was intentionally not
        traversed; it protects reconciliation but is not a failure and does not
        increment ``error_files``.
        """
        if counts_as_error:
            self.progress.error_files += 1
        if len(self.progress.errors) >= MAX_RECORDED_ERRORS:
            self._traversal_incomplete = True
            return
        self.progress.errors.append({
            "path": str(path),
            "kind": kind,
            "message": str(message)[:500],
        })

    def _reset_cancel(self) -> None:
        self._cancelled = False

    @staticmethod
    def _filesystem_device(path: Path) -> Optional[int]:
        """Return the filesystem device id for ``path``, or ``None`` if unreadable."""
        try:
            return int(path.stat().st_dev)
        except (OSError, PermissionError):
            return None

    def _fast_scan(
        self,
        path: Path,
        limit: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        include_system: bool = False,
    ) -> Iterator[FileInfo]:
        logger.info(f"Starting fast scan of {path}")
        self.progress = ScanProgress()
        self.progress.start_time = datetime.now()
        self.is_running = True

        if progress_callback:
            self.progress.current_file = f"Starting scan of {path}..."
            progress_callback(self.progress)

        file_count = 0
        batch_size = 1000
        batch = []
        self._scan_root = Path(path)
        root_device = self._filesystem_device(path)
        if root_device is None:
            self.is_running = False
            self._record_error(path, "filesystem", f"cannot determine filesystem for {path}")
            if not self._ignore_errors:
                raise OSError(f"Cannot determine filesystem for scan root: {path}")
            return

        def walk_error(error: OSError) -> None:
            """Record a directory traversal failure and keep going (partial mode).

            In strict mode the error is re-raised so the lifecycle marks the run
            FAILED and reconciliation never runs. In partial mode the subtree is
            recorded as unreadable and excluded from reconciliation.
            """
            failed_path = getattr(error, "filename", None) or path
            self._record_error(failed_path, "directory", error)
            if not self._ignore_errors:
                raise error

        try:
            for root, dirs, files in os.walk(
                str(path), onerror=walk_error, followlinks=False
            ):
                if self._cancelled:
                    break

                root_path = Path(root)
                if self._is_user_excluded_path(root_path):
                    self._record_error(root_path, "excluded", "user exclusion",
                                       counts_as_error=False)
                    dirs.clear()
                    continue
                current_device = self._filesystem_device(root_path)
                if current_device is None:
                    self._record_error(root_path, "directory",
                                       f"cannot stat directory {root_path}")
                    dirs.clear()
                    if not self._ignore_errors:
                        raise OSError(f"Cannot stat directory during scan: {root_path}")
                    continue
                if current_device != root_device:
                    logger.debug(
                        f"Skipping foreign filesystem at {root_path} "
                        f"(device={current_device}, root_device={root_device})"
                    )
                    # A nested mount point was not traversed; never infer that
                    # previously-seen paths below it were deleted.
                    self._record_error(root_path, "excluded", "foreign filesystem",
                                       counts_as_error=False)
                    dirs.clear()
                    continue

                if self._is_user_excluded_dir(root_path):
                    self._record_error(root_path, "excluded", "user exclusion",
                                       counts_as_error=False)
                    dirs.clear()
                    continue

                if self._should_skip_directory(root_path):
                    dirs.clear()
                    continue

                for filename in files:
                    if self._cancelled:
                        break
                    if limit and file_count >= limit:
                        break

                    file_path = root_path / filename
                    if self._is_user_excluded_path(file_path):
                        self._record_error(file_path, "excluded", "user exclusion",
                                           counts_as_error=False)
                        self.progress.skipped_files += 1
                        continue
                    if self._should_skip_file_fast(file_path, include_system=include_system):
                        self.progress.skipped_files += 1
                        continue

                    try:
                        file_info = self._extract_file_info_fast(file_path)
                    except (OSError, PermissionError) as exc:
                        self._record_error(file_path, "file", exc)
                        logger.warning(f"Cannot access {file_path}: {exc}")
                        continue

                    if file_info:
                        batch.append(file_info)
                        file_count += 1
                        self.progress.scanned_files = file_count
                        self.progress.scanned_bytes += file_info.size_bytes
                        self.progress.current_file = str(file_path)

                        if progress_callback:
                            should_callback = (
                                file_count % 250 == 0
                                or (
                                    (datetime.now() - self.progress.start_time).total_seconds()
                                    % 2.0
                                    < 0.1
                                )
                            )
                            if should_callback or file_count <= 10:
                                progress_callback(self.progress)

                        if len(batch) >= batch_size:
                            for item in batch:
                                yield item
                            batch.clear()

                if self._cancelled or (limit and file_count >= limit):
                    break

        except Exception:
            # Flush already discovered metadata, then propagate. The lifecycle
            # layer will mark the run FAILED and will NOT reconcile missing files.
            for item in batch:
                yield item
            batch.clear()
            raise
        else:
            for item in batch:
                yield item
            batch.clear()
            # File-level access errors are just as dangerous for reconciliation
            # as directory-level errors: an unseen existing path must not be
            # inferred to be deleted.  Raise only after yielding safe metadata.
            # In partial mode the errors are persisted per path and the
            # reconciliation layer excludes those scopes instead.
            if self.progress.error_files and not self._cancelled and not self._ignore_errors:
                raise RuntimeError(
                    f"scan incomplete: {self.progress.error_files} filesystem access errors"
                )
        finally:
            if progress_callback:
                self.progress.current_file = (
                    "Scan annulé" if self._cancelled else "Scan terminé"
                )
                progress_callback(self.progress)
            self.is_running = False
            elapsed = (datetime.now() - self.progress.start_time).total_seconds()
            logger.info(
                f"Scan ended: {file_count:,} files, "
                f"{self.progress.error_files:,} errors in {elapsed:.1f}s"
            )

    def _is_user_excluded_dir(self, dir_path: Path) -> bool:
        """Return True when a directory matches a user exclusion pattern.

        A pattern without a path separator matches the directory basename
        (case-insensitive, fnmatch globs allowed, e.g. ``node_modules`` or
        ``*.tmp``). A pattern containing a separator is matched against the
        absolute path and the path relative to the scan root.
        """
        if not self._exclude_dir_patterns:
            return False
        name = dir_path.name.lower()
        absolute = str(dir_path)
        relative = None
        if self._scan_root is not None:
            try:
                relative = str(dir_path.relative_to(self._scan_root))
            except ValueError:
                relative = None
        for pattern in self._exclude_dir_patterns:
            normalized = pattern.replace(os.sep, "/").rstrip("/")
            if "/" in normalized:
                candidates = [absolute.replace(os.sep, "/")]
                if relative is not None:
                    candidates.append(relative.replace(os.sep, "/"))
                if any(fnmatch.fnmatchcase(cand.lower(), normalized) for cand in candidates):
                    return True
                # Also honour a parent-directory prefix match (exclude a tree).
                if any(cand.lower().startswith(normalized + "/") for cand in candidates):
                    return True
            elif fnmatch.fnmatchcase(name, normalized):
                return True
        return False

    def _is_user_excluded_path(self, path: Path) -> bool:
        """Return True when a path is inside an explicitly excluded path."""
        if not self._exclude_paths:
            return False
        try:
            absolute = path.resolve()
        except OSError:
            absolute = path
        for excluded in self._exclude_paths:
            try:
                if absolute == excluded or excluded in absolute.parents:
                    return True
            except OSError:
                continue
        return False

    def _should_skip_directory(self, dir_path: Path) -> bool:
        parts = {part.lower() for part in Path(dir_path).parts}
        if parts & self._skip_dirs:
            return True
        lowered = str(dir_path).lower().replace("/", "\\")
        return "\\appdata\\local\\temp" in lowered

    def _should_skip_file_fast(
        self, file_path: Path, *, include_system: bool = False
    ) -> bool:
        """Return True for entries that must not enter the metadata index."""
        try:
            if file_path.is_symlink():
                return True
        except OSError:
            return True

        ext = file_path.suffix.lower()
        if ext in self._skip_extensions:
            return True

        if not include_system and file_path.name.startswith('.'):
            return True

        return False

    def _extract_file_info_fast(self, file_path: Path) -> Optional[FileInfo]:
        """Extract metadata for regular files only."""
        stat_result = file_path.stat()

        if not stat.S_ISREG(stat_result.st_mode):
            self.progress.skipped_files += 1
            return None

        if METADATA_INDEX_LIMIT is not None and stat_result.st_size > METADATA_INDEX_LIMIT:
            self.progress.skipped_files += 1
            return None

        return FileInfo(
            path=file_path,
            filename=file_path.name,
            size_bytes=stat_result.st_size,
            created_at=stat_created_at(stat_result),
            modified_at=datetime.fromtimestamp(stat_result.st_mtime),
            extension=file_path.suffix.lower(),
            device_id=stat_result.st_dev,
            inode=stat_result.st_ino,
            file_type=self._classify_file_type_fast(file_path.suffix.lower()),
            priority=self._determine_priority_fast(file_path),
        )

    def _classify_file_type_fast(self, extension: str) -> FileType:
        if extension in {'.pdf', '.doc', '.docx', '.xlsx', '.xls', '.ppt', '.pptx', '.rtf', '.odt', '.txt'}:
            return FileType.DOCUMENT
        if extension in {'.pst', '.ost', '.msg', '.eml', '.mbox'}:
            return FileType.EMAIL
        if extension in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heic'}:
            return FileType.IMAGE
        if extension in {'.mp4', '.avi', '.mov', '.wmv', '.mkv', '.flv', '.m4v'}:
            return FileType.VIDEO
        if extension in {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'}:
            return FileType.AUDIO
        if extension in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
            return FileType.ARCHIVE
        if extension in {'.py', '.js', '.html', '.css', '.java', '.cpp', '.c', '.php', '.rb'}:
            return FileType.CODE
        return FileType.OTHER

    def _determine_priority_fast(self, file_path: Path) -> Priority:
        ext = file_path.suffix.lower()
        for priority, extensions in self._priority_extensions.items():
            if ext in extensions:
                return priority
        filename_lower = file_path.name.lower()
        if any(word in filename_lower for word in ['contrat', 'facture', 'credit', 'pret']):
            return Priority.CRITICAL
        return Priority.MEDIUM

    def scan_paths(
        self,
        paths: list,
        limit: Optional[int] = None,
        include_system: bool = False,
        progress_callback: Optional[Callable] = None,
        *,
        ignore_errors: Optional[bool] = None,
        exclude_dirs: Optional[Sequence[str]] = None,
        exclude_paths: Optional[Sequence[str]] = None,
    ) -> Iterator[FileInfo]:
        """Scan paths while preserving cancellation and visibility options."""
        logger.info(
            f"Starting scan_paths for {len(paths)} paths with callback: "
            f"{progress_callback is not None}"
        )
        self._reset_cancel()
        self._configure(
            ignore_errors=ignore_errors,
            exclude_dirs=exclude_dirs,
            exclude_paths=exclude_paths,
        )
        for i, path in enumerate(paths):
            if self._cancelled:
                break
            logger.info(f"Scanning path {i + 1}/{len(paths)}: {path}")
            self.progress = ScanProgress()
            self.progress.start_time = datetime.now()
            yield from self._fast_scan(
                Path(path),
                limit=limit,
                progress_callback=progress_callback,
                include_system=include_system,
            )

    def pause(self) -> None:
        logger.info("Pause requested (not supported by fast scanner)")

    def resume(self) -> None:
        logger.info("Resume requested (not supported by fast scanner)")

    def cancel(self) -> None:
        self._cancelled = True
        logger.info("Scan cancelled")

    def get_scan_statistics(self) -> dict:
        return {
            'is_running': self.is_running,
            'cancelled': self._cancelled,
            'files_processed': getattr(self.progress, 'scanned_files', 0),
            'bytes_processed': getattr(self.progress, 'scanned_bytes', 0),
            'errors': getattr(self.progress, 'error_files', 0),
            'start_time': getattr(self.progress, 'start_time', None),
        }
