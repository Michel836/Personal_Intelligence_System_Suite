"""Contract tests for TurboScanner canonical persistence (M005A.1F).

TurboScanner must persist through ``DatabaseManager.save_files_batch`` so it
shares one UPSERT contract with every other scanner: metadata refresh, content
preservation, checksum/created_at preservation, and FTS trigger synchronisation.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.scanner.turbo_scan import TurboScanner


@pytest.fixture()
def turbo(tmp_path: Path) -> TurboScanner:
    scanner = TurboScanner()
    scanner.db = DatabaseManager(tmp_path / "turbo.db")
    return scanner


def test_turbo_initial_scan_inserts_rows(turbo: TurboScanner, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "one.txt").write_text("body one", encoding="utf-8")
    (root / "two.pdf").write_bytes(b"%PDF-1.4")

    stats = turbo.turbo_scan(root)

    rows = turbo.db.search_files(limit=100)
    assert stats is not None
    assert len(rows) == 2
    assert {r["filename"] for r in rows} == {"one.txt", "two.pdf"}


def test_turbo_repeat_scan_keeps_one_row_and_refreshes(
    turbo: TurboScanner, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "one.txt"
    target.write_text("short", encoding="utf-8")

    turbo.turbo_scan(root)
    original = turbo.db.search_files()[0]
    first_size = original["size_bytes"]

    time.sleep(0.01)
    target.write_text("much longer body content", encoding="utf-8")
    turbo.turbo_scan(root)

    rows = turbo.db.search_files()
    assert len(rows) == 1
    assert rows[0]["id"] == original["id"]
    assert rows[0]["size_bytes"] > first_size


def test_turbo_preserves_content_checksum_and_created_at(
    turbo: TurboScanner, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "one.txt").write_text("body", encoding="utf-8")

    turbo.turbo_scan(root)
    file_id = turbo.db.search_files()[0]["id"]
    turbo.db.update_content(file_id, "extracted turbo content")
    with turbo.db.get_connection() as conn:
        conn.execute(
            "UPDATE files SET checksum='keepme', created_at='2010-05-05T00:00:00' WHERE id=?",
            (file_id,),
        )
        conn.commit()

    # A second turbo scan carries no hash/birth time; known values must survive.
    turbo.turbo_scan(root)

    row = turbo.db.search_files()[0]
    assert row["content_text"] == "extracted turbo content"
    assert row["checksum"] == "keepme"
    assert row["created_at"].startswith("2010-05-05")
    assert len(turbo.db.search_files(query="extracted")) == 1


def test_turbo_fts_and_sqlite_integrity(turbo: TurboScanner, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "alpha_note.txt").write_text("x", encoding="utf-8")

    turbo.turbo_scan(root)

    with turbo.db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('integrity-check')")


def test_modern_app_still_uses_turbo_interface() -> None:
    """Static caller-contract check (no UI launch)."""
    text = Path("src/ui/modern_app.py").read_text(encoding="utf-8")
    assert "from src.scanner.turbo_scan import TurboScanner" in text
    assert "turbo.turbo_scan(" in text
