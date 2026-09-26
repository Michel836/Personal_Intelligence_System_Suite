"""Optimized fast scanner engine."""

import hashlib
import time
from pathlib import Path
from typing import Iterator, Optional, Callable
from collections import Counter
from datetime import datetime
import os

from loguru import logger
from .models import (
    FileInfo,
    FileType,
    Priority,
    ScanProgress,
    ScanStats,
    METADATA_INDEX_LIMIT,
    stat_created_at,
)


class FastScannerEngine:
    """High-speed file scanner optimized for performance."""
    
    def __init__(self):
        self.progress = ScanProgress()
        self.is_running = False
        self._cancelled = False
        
        # Priority file extensions
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
        
        # Skip extensions (harmonized with ScannerEngine)
        self._skip_extensions = {
            '.dll', '.sys', '.exe', '.msi', '.tmp', '.log',
            '.cache', '.lock', '.pid', '.swp', '.~', '.lnk',
            '.bak', '.temp'
        }
        
        # System directories to skip
        # Matched as whole path components (see _should_skip_directory), never
        # as substrings, so directories like ~/recovery_notes or
        # "project-recovery-tool" stay indexed.
        self._skip_dirs = {
            # OS system directories
            'windows', 'program files', 'program files (x86)',
            'programdata', '$recycle.bin', 'system volume information',
            'windows.old', 'recovery',
            # VCS / virtualenv / build / cache directories (not source content)
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
        progress_callback: Optional[Callable] = None
    ) -> Iterator[FileInfo]:
        """Ultra-fast single-pass scan.

        Each call starts from a clean cancellation state so a previous
        ``cancel()`` cannot permanently disable scanning.
        """
        self._reset_cancel()
        yield from self._fast_scan(path, limit=limit, progress_callback=progress_callback)

    def _reset_cancel(self) -> None:
        """Clear the cancellation flag for a new scan invocation."""
        self._cancelled = False

    def _fast_scan(
        self,
        path: Path,
        limit: Optional[int] = None,
        progress_callback: Optional[Callable] = None
    ) -> Iterator[FileInfo]:
        logger.info(f"Starting fast scan of {path}")
        self.progress = ScanProgress()
        self.progress.start_time = datetime.now()
        self.is_running = True
        
        # Initial callback to show scan has started
        if progress_callback:
            self.progress.current_file = f"Starting scan of {path}..."
            logger.debug("Initial progress callback - scan starting")
            progress_callback(self.progress)
        
        file_count = 0
        batch_size = 1000
        batch = []
        
        try:
            # Single pass with os.walk (much faster than pathlib.rglob)
            for root, dirs, files in os.walk(str(path)):
                # Skip system directories
                if self._should_skip_directory(Path(root)):
                    dirs.clear()  # Don't recurse into subdirs
                    continue
                
                # Process files in current directory
                for filename in files:
                    if self._cancelled:
                        break
                        
                    if limit and file_count >= limit:
                        break
                    
                    file_path = Path(root) / filename
                    
                    # Quick skip check
                    if self._should_skip_file_fast(file_path):
                        self.progress.skipped_files += 1
                        continue
                    
                    # Fast file info extraction
                    file_info = self._extract_file_info_fast(file_path)
                    if file_info:
                        batch.append(file_info)
                        file_count += 1
                        
                        # Progress update
                        self.progress.scanned_files = file_count
                        self.progress.scanned_bytes += file_info.size_bytes
                        self.progress.current_file = str(file_path)
                        
                        # Progress callback - improved frequency and data  
                        if progress_callback:
                            # Call every 250 files OR every 2 seconds (whichever comes first)
                            should_callback = (file_count % 250 == 0) or \
                                            ((datetime.now() - self.progress.start_time).total_seconds() % 2.0 < 0.1)
                            
                            if should_callback or file_count <= 10:  # Always callback for first 10 files
                                # Update progress with current state (files_per_second is auto-calculated)
                                self.progress.current_file = str(file_path)
                                logger.debug(f"Progress callback: {file_count} files processed")
                                progress_callback(self.progress)
                        
                        # Batch yield for better performance
                        if len(batch) >= batch_size:
                            for item in batch:
                                yield item
                            batch.clear()
                
                if limit and file_count >= limit:
                    break
        
        except Exception as e:
            logger.error(f"Scan error: {e}")
        finally:
            # Yield remaining files
            for item in batch:
                yield item
            
            # Final progress callback
            if progress_callback:
                self.progress.current_file = "Scan terminé"
                progress_callback(self.progress)
            
            self.is_running = False
            elapsed = (datetime.now() - self.progress.start_time).total_seconds()
            logger.info(f"Scan completed: {file_count:,} files in {elapsed:.1f}s")
    
    def _should_skip_directory(self, dir_path: Path) -> bool:
        """Quick directory skip check.

        Matches *path components* (case-insensitive), not arbitrary substrings,
        so a legitimate path such as ``~/recovery_notes`` or ``~/windows-notes``
        is not silently pruned from the index.
        """
        parts = {part.lower() for part in Path(dir_path).parts}
        if parts & self._skip_dirs:
            return True
        lowered = str(dir_path).lower().replace("/", "\\")
        return "\\appdata\\local\\temp" in lowered
    
    def _should_skip_file_fast(self, file_path: Path) -> bool:
        """Ultra-fast file skip check."""
        # Skip by extension
        ext = file_path.suffix.lower()
        if ext in self._skip_extensions:
            return True
        
        # Skip hidden files
        if file_path.name.startswith('.'):
            return True
        
        # Skip very large files quickly (no stat call yet)
        return False
    
    def _extract_file_info_fast(self, file_path: Path) -> Optional[FileInfo]:
        """Fast file information extraction with timeout protection."""
        try:
            # Single stat() call with timeout protection
            stat_result = file_path.stat()
            
            # Metadata is indexed for every size unless a limit is configured.
            if METADATA_INDEX_LIMIT is not None and stat_result.st_size > METADATA_INDEX_LIMIT:
                return None

            # Build FileInfo quickly
            file_info = FileInfo(
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
                # Skip expensive operations:
                # - No MIME detection
                # - No checksum calculation  
                # - No accessed_at (not reliable on Windows anyway)
            )
            
            return file_info
            
        except (OSError, PermissionError) as e:
            logger.debug(f"Cannot access {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return None
    
    def _classify_file_type_fast(self, extension: str) -> FileType:
        """Fast file type classification by extension only."""
        
        # Document types
        if extension in {'.pdf', '.doc', '.docx', '.xlsx', '.xls', '.ppt', '.pptx', '.rtf', '.odt', '.txt'}:
            return FileType.DOCUMENT
        
        # Email types  
        if extension in {'.pst', '.ost', '.msg', '.eml', '.mbox'}:
            return FileType.EMAIL
        
        # Image types
        if extension in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heic'}:
            return FileType.IMAGE
        
        # Video types
        if extension in {'.mp4', '.avi', '.mov', '.wmv', '.mkv', '.flv', '.m4v'}:
            return FileType.VIDEO
        
        # Audio types
        if extension in {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'}:
            return FileType.AUDIO
        
        # Archive types
        if extension in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
            return FileType.ARCHIVE
        
        # Code types
        if extension in {'.py', '.js', '.html', '.css', '.java', '.cpp', '.c', '.php', '.rb'}:
            return FileType.CODE
        
        return FileType.OTHER
    
    def _determine_priority_fast(self, file_path: Path) -> Priority:
        """Fast priority determination."""
        ext = file_path.suffix.lower()
        
        # Check priority extensions
        for priority, extensions in self._priority_extensions.items():
            if ext in extensions:
                return priority
        
        # Quick filename check for legal docs
        filename_lower = file_path.name.lower()
        if any(word in filename_lower for word in ['contrat', 'facture', 'credit', 'pret']):
            return Priority.CRITICAL
        
        return Priority.MEDIUM
    
    def scan_paths(
        self, 
        paths: list, 
        limit: Optional[int] = None, 
        include_system: bool = False,
        progress_callback: Optional[Callable] = None
    ) -> Iterator[FileInfo]:
        """Compatibility method that calls fast_scan for each path with proper callback."""
        logger.info(f"Starting scan_paths for {len(paths)} paths with callback: {progress_callback is not None}")

        # Reset cancellation once per invocation so a mid-scan cancel applies to
        # all remaining roots, while a new invocation starts fresh.
        self._reset_cancel()

        for i, path in enumerate(paths):
            logger.info(f"Scanning path {i+1}/{len(paths)}: {path}")
            
            # Reset progress for each path to ensure callbacks work
            self.progress = ScanProgress()
            self.progress.start_time = datetime.now()
            
            yield from self._fast_scan(Path(path), limit=limit, progress_callback=progress_callback)
    
    def pause(self) -> None:
        """Pause is not supported by FastScannerEngine; no-op for compatibility."""
        logger.info("Pause requested (not supported by fast scanner)")
    
    def resume(self) -> None:
        """Resume is not supported by FastScannerEngine; no-op for compatibility."""
        logger.info("Resume requested (not supported by fast scanner)")
    
    def cancel(self) -> None:
        """Cancel the scan."""
        self._cancelled = True
        logger.info("Scan cancelled")
    
    def get_scan_statistics(self) -> dict:
        """Get current scan statistics."""
        return {
            'is_running': self.is_running,
            'cancelled': self._cancelled,
            'files_processed': getattr(self.progress, 'scanned_files', 0),
            'bytes_processed': getattr(self.progress, 'scanned_bytes', 0),
            'start_time': getattr(self.progress, 'start_time', None)
        }