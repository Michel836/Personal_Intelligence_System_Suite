"""Core scanner engine for 36TB Intelligence."""

import hashlib
try:
    import magic
except ImportError:
    magic = None
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator, List, Optional, Set, Callable
from collections import defaultdict, Counter
from datetime import datetime

from loguru import logger
from ..core.simple_config import settings
from ..core.logging import log_performance
from .models import FileInfo, FileType, Priority, ScanProgress, ScanStats


class ScannerEngine:
    """High-performance file scanner with prioritization and filtering."""
    
    def __init__(self, max_workers: Optional[int] = None):
        self.max_workers = max_workers or settings.max_workers
        self.progress = ScanProgress()
        self.is_running = False
        self._cancelled = False
        self._paused = False
        
        # Initialize magic for MIME detection with fallback
        try:
            self._magic = magic.Magic(mime=True) if magic else None
        except Exception as e:
            logger.warning(f"Failed to initialize magic MIME detection: {e}")
            self._magic = None
        
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
            },
            Priority.MEDIUM: {
                '.mp3', '.wav', '.flac', '.html', '.xml', '.json'
            },
            Priority.LOW: {
                '.tmp', '.log', '.bak', '.cache', '.temp'
            }
        }
        
        # Extensions to skip (harmonized with FastScannerEngine)
        self._skip_extensions = {
            '.dll', '.sys', '.exe', '.msi', '.tmp', '.log',
            '.cache', '.lock', '.pid', '.swp', '.~', '.lnk',
            '.bak', '.temp'
        }
    
    def scan_paths(
        self,
        paths: List[Path],
        limit: Optional[int] = None,
        include_system: bool = False,
        progress_callback: Optional[Callable[[ScanProgress], None]] = None
    ) -> Iterator[FileInfo]:
        """Scan multiple paths with progress tracking."""
        
        logger.info(f"Starting scan of {len(paths)} paths")
        self._reset_progress()
        self.is_running = True
        
        try:
            # First pass: count total files for progress
            if limit:
                logger.info(f"Quick count (limit: {limit:,})")
            else:
                logger.info("Counting total files...")
                
            total_files = self._count_files(paths, limit, include_system)
            self.progress.total_files = total_files
            logger.info(f"Found {total_files:,} files to scan")
            
            # Second pass: scan files
            scanned_count = 0
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit scan tasks
                futures = {}
                
                for path in paths:
                    for file_path in self._walk_directory(path, include_system):
                        if limit and scanned_count >= limit:
                            break
                            
                        if self._should_skip_file(file_path):
                            self.progress.skipped_files += 1
                            continue
                        
                        future = executor.submit(self._scan_file, file_path)
                        futures[future] = file_path
                        
                        # Improved batch processing with dynamic sizing
                        max_futures = min(self.max_workers * 4, 100)  # Better scaling
                        if len(futures) >= max_futures:
                            yield from self._process_completed_futures(
                                futures, progress_callback
                            )
                
                # Process remaining futures
                yield from self._process_completed_futures(
                    futures, progress_callback, final=True
                )
        
        finally:
            self.is_running = False
            logger.info(f"Scan completed: {self.progress.scanned_files:,} files")
    
    def scan_single_path(
        self,
        path: Path,
        limit: Optional[int] = None,
        include_system: bool = False
    ) -> ScanStats:
        """Scan a single path and return statistics."""
        
        files = list(self.scan_paths([path], limit, include_system))
        return self._calculate_stats(files)
    
    def _reset_progress(self) -> None:
        """Reset progress tracking."""
        self.progress = ScanProgress()
        self._cancelled = False
        self._paused = False
    
    def _count_files(
        self, 
        paths: List[Path], 
        limit: Optional[int],
        include_system: bool
    ) -> int:
        """Count total files to scan."""
        count = 0
        
        for path in paths:
            for file_path in self._walk_directory(path, include_system):
                if limit and count >= limit:
                    break
                    
                if not self._should_skip_file(file_path):
                    count += 1
        
        return min(count, limit) if limit else count
    
    def _walk_directory(
        self, 
        path: Path, 
        include_system: bool
    ) -> Iterator[Path]:
        """Walk directory tree efficiently."""
        
        try:
            # Skip system directories unless requested
            if not include_system and self._is_system_path(path):
                return
            
            for item in path.rglob("*"):
                if self._cancelled:
                    break
                    
                while self._paused:
                    time.sleep(0.1)
                
                if item.is_file():
                    yield item
                    
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot access {path}: {e}")
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        
        # Skip by extension
        if file_path.suffix.lower() in self._skip_extensions:
            return True
        
        # Skip hidden files (optional)
        if file_path.name.startswith('.'):
            return True
        
        # Skip by size (unified limit: 1GB)
        try:
            size_bytes = file_path.stat().st_size
            if size_bytes > 1024 * 1024 * 1024:  # 1GB limit
                logger.debug(f"Skipping large file: {file_path} ({size_bytes / (1024**3):.2f}GB)")
                return True
        except OSError:
            return True
        
        return False
    
    def _is_system_path(self, path: Path) -> bool:
        """Check if path is a system directory."""
        
        system_dirs = {
            'windows', 'program files', 'program files (x86)',
            'programdata', '$recycle.bin', 'system volume information'
        }
        
        return any(part.lower() in system_dirs for part in path.parts)
    
    @log_performance()
    def _scan_file(self, file_path: Path) -> Optional[FileInfo]:
        """Scan a single file and extract metadata."""
        
        try:
            stat_info = file_path.stat()
            
            # Basic file info
            file_info = FileInfo(
                path=file_path,
                filename=file_path.name,
                size_bytes=stat_info.st_size,
                created_at=datetime.fromtimestamp(stat_info.st_ctime),
                modified_at=datetime.fromtimestamp(stat_info.st_mtime),
                accessed_at=datetime.fromtimestamp(stat_info.st_atime),
                extension=file_path.suffix.lower(),
            )
            
            # MIME type detection
            try:
                if self._magic:
                    file_info.mime_type = self._magic.from_file(str(file_path))
                else:
                    file_info.mime_type = None
            except Exception as e:
                logger.debug(f"MIME detection failed for {file_path}: {e}")
                file_info.mime_type = None
            
            # File type classification
            file_info.file_type = self._classify_file_type(file_info)
            
            # Priority assignment
            file_info.priority = self._determine_priority(file_info)
            
            # Content hash (for small files only, with memory protection)
            if file_info.size_bytes < 50 * 1024 * 1024:  # < 50MB (reasonable limit)
                file_info.checksum = self._calculate_checksum_safe(file_path, file_info.size_bytes)
            
            # Detect special characteristics
            self._detect_file_characteristics(file_info)
            
            return file_info
            
        except Exception as e:
            logger.error(f"Error scanning {file_path}: {e}")
            return None
    
    def _classify_file_type(self, file_info: FileInfo) -> FileType:
        """Classify file type based on extension and MIME type."""
        
        ext = file_info.extension
        mime = file_info.mime_type or ""
        
        # Document types
        if ext in {'.pdf', '.doc', '.docx', '.xlsx', '.xls', '.ppt', '.pptx', '.rtf', '.odt', '.txt'}:
            return FileType.DOCUMENT
        
        # Email types  
        if ext in {'.pst', '.ost', '.msg', '.eml', '.mbox'}:
            return FileType.EMAIL
        
        # Image types
        if ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'} or mime.startswith('image/'):
            return FileType.IMAGE
        
        # Video types
        if ext in {'.mp4', '.avi', '.mov', '.wmv', '.mkv', '.flv'} or mime.startswith('video/'):
            return FileType.VIDEO
        
        # Audio types
        if ext in {'.mp3', '.wav', '.flac', '.aac', '.ogg'} or mime.startswith('audio/'):
            return FileType.AUDIO
        
        # Archive types
        if ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
            return FileType.ARCHIVE
        
        # Code types
        if ext in {'.py', '.js', '.html', '.css', '.java', '.cpp', '.c', '.php', '.rb'}:
            return FileType.CODE
        
        return FileType.OTHER
    
    def _determine_priority(self, file_info: FileInfo) -> Priority:
        """Determine file priority based on type and extension."""
        
        ext = file_info.extension
        
        # Check each priority level
        for priority, extensions in self._priority_extensions.items():
            if ext in extensions:
                return priority
        
        # Special logic for legal/financial keywords in filename
        filename_lower = file_info.filename.lower()
        legal_keywords = {
            'contrat', 'contract', 'accord', 'agreement', 'facture', 'invoice',
            'credit', 'loan', 'pret', 'hypotheque', 'mortgage', 'notaire',
            'avocat', 'lawyer', 'tribunal', 'court'
        }
        
        if any(keyword in filename_lower for keyword in legal_keywords):
            return Priority.CRITICAL
        
        return Priority.MEDIUM
    
    def _calculate_checksum_safe(self, file_path: Path, file_size: int) -> str:
        """Calculate MD5 checksum of file with memory and time protection."""
        
        try:
            # Additional safety check
            if file_size > 50 * 1024 * 1024:  # 50MB
                return ""
            
            hash_md5 = hashlib.md5()
            bytes_read = 0
            max_bytes = 50 * 1024 * 1024  # Hard limit
            
            with open(file_path, "rb") as f:
                while bytes_read < max_bytes:
                    chunk = f.read(8192)  # Larger chunks for efficiency
                    if not chunk:
                        break
                    hash_md5.update(chunk)
                    bytes_read += len(chunk)
                    
                    # Safety break if file is larger than expected
                    if bytes_read > file_size * 1.1:  # 10% tolerance
                        break
                        
            return hash_md5.hexdigest()
        except Exception as e:
            logger.debug(f"Checksum calculation failed for {file_path}: {e}")
            return ""
    
    def _detect_file_characteristics(self, file_info: FileInfo) -> None:
        """Detect special file characteristics."""
        
        # Check if file might need OCR (scanned PDFs, images with text)
        if file_info.file_type in {FileType.IMAGE, FileType.DOCUMENT}:
            file_info.requires_ocr = True
        
        # Check for encrypted files (basic heuristics)
        if file_info.extension in {'.zip', '.rar', '.7z'}:
            # TODO: Implement encryption detection
            pass
    
    def _process_completed_futures(
        self,
        futures: dict,
        progress_callback: Optional[Callable],
        final: bool = False
    ) -> Iterator[FileInfo]:
        """Process completed scanning futures."""
        
        completed_futures = []
        
        if final:
            # Wait for all remaining futures
            for future in as_completed(futures.keys()):
                completed_futures.append(future)
        else:
            # Process only completed futures
            for future in list(futures.keys()):
                if future.done():
                    completed_futures.append(future)
        
        for future in completed_futures:
            file_path = futures.pop(future)
            
            try:
                file_info = future.result()
                if file_info:
                    self.progress.scanned_files += 1
                    self.progress.scanned_bytes += file_info.size_bytes
                    self.progress.current_file = str(file_path)
                    
                    if progress_callback:
                        progress_callback(self.progress)
                    
                    yield file_info
                else:
                    self.progress.error_files += 1
                    
            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
                self.progress.error_files += 1
    
    def _calculate_stats(self, files: List[FileInfo]) -> ScanStats:
        """Calculate comprehensive scan statistics."""
        
        if not files:
            return ScanStats(
                total_files=0,
                total_bytes=0,
                unique_files=0,
                duplicate_files=0,
                error_files=0,
                scan_duration_seconds=self.progress.elapsed_seconds,
                files_per_second=0,
                mb_per_second=0
            )
        
        # Basic counts
        total_files = len(files)
        total_bytes = sum(f.size_bytes for f in files)
        
        # Corrected duplicate detection by checksum
        checksums = [f.checksum for f in files if f.checksum]
        unique_checksums = set(checksums)
        
        # Count actual duplicates properly
        checksum_counts = {}
        for checksum in checksums:
            checksum_counts[checksum] = checksum_counts.get(checksum, 0) + 1
        
        duplicate_files = sum(count - 1 for count in checksum_counts.values() if count > 1)
        unique_files = total_files - duplicate_files
        
        # Distribution analysis
        file_types = Counter(f.file_type for f in files)
        extensions = Counter(f.extension for f in files)
        priorities = Counter(f.priority for f in files)
        
        # Size ranges
        size_ranges = defaultdict(int)
        for file_info in files:
            mb = file_info.size_mb
            if mb < 1:
                size_ranges["< 1MB"] += 1
            elif mb < 10:
                size_ranges["1-10MB"] += 1
            elif mb < 100:
                size_ranges["10-100MB"] += 1
            else:
                size_ranges["> 100MB"] += 1
        
        # Year distribution
        year_distribution = Counter(
            f.modified_at.year for f in files if f.modified_at
        )
        
        # Performance metrics
        duration = self.progress.elapsed_seconds
        files_per_sec = total_files / duration if duration > 0 else 0
        mb_per_sec = (total_bytes / (1024*1024)) / duration if duration > 0 else 0
        
        # Top files
        files_by_size = sorted(files, key=lambda f: f.size_bytes, reverse=True)
        files_by_age = sorted(files, key=lambda f: f.modified_at or datetime.min)
        files_by_recent = sorted(files, key=lambda f: f.modified_at or datetime.min, reverse=True)
        
        return ScanStats(
            total_files=total_files,
            total_bytes=total_bytes,
            unique_files=unique_files,
            duplicate_files=duplicate_files,
            error_files=self.progress.error_files,
            
            file_types=dict(file_types),
            extensions=dict(extensions.most_common(20)),
            priorities=dict(priorities),
            size_ranges=dict(size_ranges),
            year_distribution=dict(year_distribution),
            
            scan_duration_seconds=duration,
            files_per_second=files_per_sec,
            mb_per_second=mb_per_sec,
            
            largest_files=files_by_size[:10],
            oldest_files=files_by_age[:10],
            newest_files=files_by_recent[:10],
        )
    
    def pause(self) -> None:
        """Pause the scanning process."""
        self._paused = True
        self.progress.is_paused = True
        logger.info("Scan paused")
    
    def resume(self) -> None:
        """Resume the scanning process."""
        self._paused = False
        self.progress.is_paused = False
        logger.info("Scan resumed")
    
    def cancel(self) -> None:
        """Cancel the scanning process."""
        self._cancelled = True
        self.progress.is_cancelled = True
        logger.info("Scan cancelled")
    
    def validate_scan_settings(self, paths: List[Path]) -> dict:
        """Validate scan settings and return recommendations."""
        validation_result = {
            'valid': True,
            'warnings': [],
            'errors': [],
            'recommendations': []
        }
        
        # Check paths
        for path in paths:
            if not path.exists():
                validation_result['errors'].append(f"Path does not exist: {path}")
                validation_result['valid'] = False
            elif not path.is_dir():
                validation_result['warnings'].append(f"Path is not a directory: {path}")
        
        # Check available memory
        try:
            import psutil
            available_memory_gb = psutil.virtual_memory().available / (1024**3)
            if available_memory_gb < 2:
                validation_result['warnings'].append(
                    f"Low available memory: {available_memory_gb:.1f}GB"
                )
                validation_result['recommendations'].append(
                    "Consider reducing max_workers or using FastScannerEngine"
                )
        except ImportError:
            validation_result['recommendations'].append(
                "Install psutil for memory monitoring"
            )
        
        # Check thread settings
        if self.max_workers > 8:
            validation_result['warnings'].append(
                f"High thread count: {self.max_workers} workers"
            )
            validation_result['recommendations'].append(
                "Consider reducing max_workers for better stability"
            )
        
        return validation_result