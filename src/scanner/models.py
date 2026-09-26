"""Data models for scanner module."""

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum

# Size policy. These thresholds are deliberately independent so that metadata
# visibility is never sacrificed for expensive hashing/extraction.
METADATA_INDEX_LIMIT: Optional[int] = None  # index metadata for any size
HASH_LIMIT = 50 * 1024 * 1024               # 50 MiB
EXTRACTION_LIMIT = 50 * 1024 * 1024         # 50 MiB


def stat_created_at(stat_result: Any) -> Optional[datetime]:
    """Return a real creation time, or ``None`` when unavailable.

    On Linux ``st_ctime`` is the inode *change* time (updated by chmod/rename),
    not creation/birth time, so it must never be reported as ``created_at``.
    """
    birth = getattr(stat_result, "st_birthtime", None)
    return datetime.fromtimestamp(birth) if birth else None


class FileType(str, Enum):
    """File type enumeration."""
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    EMAIL = "email"
    CODE = "code"
    OTHER = "other"


class Priority(str, Enum):
    """Scan priority levels."""
    CRITICAL = "critical"  # Legal, financial docs
    HIGH = "high"         # Important documents
    MEDIUM = "medium"     # General documents
    LOW = "low"          # Media, temp files


class FileInfo(BaseModel):
    """Information about a scanned file."""
    
    path: Path
    filename: str
    size_bytes: int
    created_at: Optional[datetime] = None
    modified_at: datetime
    accessed_at: Optional[datetime] = None
    
    # File characteristics
    extension: str
    mime_type: Optional[str] = None
    file_type: FileType = FileType.OTHER
    encoding: Optional[str] = None
    
    # Scan metadata
    priority: Priority = Priority.MEDIUM
    scan_timestamp: datetime = Field(default_factory=datetime.now)
    checksum: Optional[str] = None
    
    # Flags
    is_duplicate: bool = False
    is_corrupted: bool = False
    is_encrypted: bool = False
    requires_ocr: bool = False
    
    # Custom attributes
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        json_encoders = {
            Path: str,
            datetime: lambda v: v.isoformat(),
        }
    
    @property
    def size_mb(self) -> float:
        """File size in MB."""
        return self.size_bytes / (1024 * 1024)
    
    @property
    def age_days(self) -> int:
        """File age in days."""
        return (datetime.now() - self.modified_at).days


class ScanProgress(BaseModel):
    """Scan progress information."""
    
    total_files: int = 0
    scanned_files: int = 0
    error_files: int = 0
    skipped_files: int = 0
    
    total_bytes: int = 0
    scanned_bytes: int = 0
    
    start_time: datetime = Field(default_factory=datetime.now)
    current_file: Optional[str] = None
    
    is_running: bool = False
    is_paused: bool = False
    is_cancelled: bool = False
    
    @property
    def progress_percent(self) -> float:
        """Progress as percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.scanned_files / self.total_files) * 100
    
    @property
    def elapsed_seconds(self) -> float:
        """Elapsed time in seconds."""
        return (datetime.now() - self.start_time).total_seconds()
    
    @property
    def files_per_second(self) -> float:
        """Scanning speed in files per second."""
        elapsed = self.elapsed_seconds
        if elapsed == 0:
            return 0.0
        return self.scanned_files / elapsed
    
    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimated time to completion in seconds."""
        if self.files_per_second == 0 or self.total_files == 0:
            return None
        remaining = self.total_files - self.scanned_files
        return remaining / self.files_per_second


class ScanStats(BaseModel):
    """Statistics from a completed scan."""
    
    # Basic counts
    total_files: int
    total_bytes: int
    unique_files: int
    duplicate_files: int
    error_files: int
    
    # By file type
    file_types: Dict[FileType, int] = Field(default_factory=dict)
    extensions: Dict[str, int] = Field(default_factory=dict)
    
    # By priority
    priorities: Dict[Priority, int] = Field(default_factory=dict)
    
    # Size distribution
    size_ranges: Dict[str, int] = Field(default_factory=dict)
    
    # Time distribution
    year_distribution: Dict[int, int] = Field(default_factory=dict)
    
    # Performance metrics
    scan_duration_seconds: float
    files_per_second: float
    mb_per_second: float
    
    # Top files
    largest_files: list[FileInfo] = Field(default_factory=list)
    oldest_files: list[FileInfo] = Field(default_factory=list)
    newest_files: list[FileInfo] = Field(default_factory=list)
    
    @property
    def total_gb(self) -> float:
        """Total size in GB."""
        return self.total_bytes / (1024 ** 3)
    
    @property
    def duplicate_percent(self) -> float:
        """Percentage of duplicate files."""
        if self.total_files == 0:
            return 0.0
        return (self.duplicate_files / self.total_files) * 100
    
    def get_summary(self) -> str:
        """Get a human-readable summary."""
        return f"""
Scan Summary:
============
📁 Files: {self.total_files:,} ({self.unique_files:,} unique)
💾 Size: {self.total_gb:.2f} GB
⏱️  Duration: {self.scan_duration_seconds:.1f}s
🚀 Speed: {self.files_per_second:.0f} files/sec
📊 Duplicates: {self.duplicate_files:,} ({self.duplicate_percent:.1f}%)
❌ Errors: {self.error_files:,}
        """.strip()