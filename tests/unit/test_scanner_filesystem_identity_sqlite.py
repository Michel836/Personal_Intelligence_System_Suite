"""Compatibility alias for the filesystem-identity SQLite suite.

SCAN-UI-01 validation refers to ``test_scanner_filesystem_identity_sqlite.py``
while the canonical coverage lives in ``test_filesystem_identity_sqlite.py``.
Re-exporting the tests keeps a single source of truth for the unsigned-inode /
SQLite int64 normalization contract instead of duplicating it.
"""
from __future__ import annotations

from tests.unit.test_filesystem_identity_sqlite import (  # noqa: F401
    test_fileinfo_normalizes_portal_inode,
    test_identity_outside_uint64_range_is_rejected,
    test_identity_values_already_in_sqlite_range_are_unchanged,
    test_unsigned_inode_maps_to_signed_sqlite_int64,
)
