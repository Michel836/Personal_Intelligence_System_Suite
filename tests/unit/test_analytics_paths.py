"""Analytics exports must honour the canonical reports directory (M022)."""
from __future__ import annotations

from pathlib import Path

from src.analytics.dashboard import AnalyticsDashboard
from src.core.database import DatabaseManager
from src.core.paths import reports_dir


def _db(tmp_path: Path) -> Path:
    db = DatabaseManager(tmp_path / "analytics.db")
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (path, filename, extension, size_bytes, modified_at, "
            "state, document_kind, file_type) VALUES "
            "('/corpus/a.txt', 'a.txt', '.txt', 120, '2024-01-01', 'ACTIVE', "
            "'PHYSICAL_FILE', 'document')"
        )
        conn.commit()
    return db.db_path


def test_export_stats_uses_reports_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_DATA_DIR", str(tmp_path / "data"))
    dashboard = AnalyticsDashboard(db_path=str(_db(tmp_path)))
    output = dashboard.export_stats()
    assert output, "export should produce a path"
    assert Path(output).is_absolute()
    assert Path(output).parent == reports_dir()
    assert Path(output).is_file()
