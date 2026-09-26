#!/usr/bin/env python3
"""List files marked MISSING (not seen in a completed scan).

Recovery/diagnostic helper. Read-only; never deletes rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager  # noqa: E402


def main() -> int:
    db = DatabaseManager()
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT filename, path, state, last_seen_scan_id
               FROM files WHERE state = 'MISSING'
               ORDER BY path"""
        ).fetchall()
    if not rows:
        print("No MISSING files. Index is consistent with the last completed scans.")
        return 0
    print(f"{len(rows)} MISSING file(s):")
    for row in rows:
        print(f"  [{row['state']}] {row['path']} (last_seen_scan_id={row['last_seen_scan_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
