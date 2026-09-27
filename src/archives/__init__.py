"""Safe archive inspection and virtual-member support (M009J).

Archives are treated as *containers*: their members become virtual documents
that are searched alongside physical files, but member paths are never treated
as real filesystem paths and members are never extracted back into a source
directory.
"""

from .inspector import (
    ARCHIVE_FORMATS,
    ArchiveFormat,
    ArchiveInspector,
    ArchiveMember,
    ArchiveStatus,
    MemberType,
    detect_format,
    sanitize_member_path,
    virtual_path,
)
from .limits import ArchiveLimits, ArchivePolicy

__all__ = [
    "ARCHIVE_FORMATS",
    "ArchiveFormat",
    "ArchiveInspector",
    "ArchiveLimits",
    "ArchiveMember",
    "ArchivePolicy",
    "ArchiveStatus",
    "MemberType",
    "detect_format",
    "sanitize_member_path",
    "virtual_path",
]
