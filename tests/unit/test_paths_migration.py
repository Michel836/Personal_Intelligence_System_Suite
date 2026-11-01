"""XDG path resolution and legacy ``./data`` migration (Week 2, point 4)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core import paths


def _only(*items: Path):
    """Return a stub callable that ignores its arguments and returns *items*."""

    def _candidates(*args, **kwargs):  # noqa: ARG001 - signature compatibility
        return list(items)

    return _candidates


def _make_legacy_db(root: Path) -> Path:
    db = root / "indexes" / "files.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT)")
    conn.execute("INSERT INTO files (path) VALUES ('/legacy/a.txt')")
    conn.commit()
    conn.close()
    (root / "reports").mkdir()
    (root / "reports" / "old.html").write_text("<html>old</html>", encoding="utf-8")
    return db


def test_default_paths_are_absolute_and_xdg_based(monkeypatch) -> None:
    monkeypatch.setenv("PIS_DATA_DIR", "/tmp/pis-xdg-test/data")
    monkeypatch.delenv("PIS_DB_PATH", raising=False)
    assert paths.data_dir() == Path("/tmp/pis-xdg-test/data")
    assert paths.default_db_path() == "/tmp/pis-xdg-test/data/indexes/files.db"
    assert paths.embeddings_dir().is_absolute()
    assert paths.export_dir().is_absolute()


def test_resolve_db_path_explicit_wins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PIS_DATA_DIR", str(tmp_path / "data"))
    explicit = tmp_path / "explicit.db"
    assert paths.resolve_db_path(explicit) == explicit
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "env.db"))
    assert paths.resolve_db_path() == tmp_path / "env.db"


def test_sqlite_migration_is_consistent_and_moves(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "legacy"
    _make_legacy_db(legacy)
    target = tmp_path / "xdg"
    monkeypatch.setenv("PIS_DATA_DIR", str(target))

    report = paths.migrate_legacy_data(legacy, move=True)
    assert report["status"] == "MOVED"
    assert report["sqlite"] == 1

    migrated_db = target / "indexes" / "files.db"
    assert migrated_db.is_file()
    conn = sqlite3.connect(migrated_db)
    try:
        assert conn.execute("SELECT path FROM files").fetchone()[0] == "/legacy/a.txt"
    finally:
        conn.close()
    assert (target / "reports" / "old.html").is_file()
    assert not legacy.exists()


def test_migration_copy_keeps_source(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "legacy"
    _make_legacy_db(legacy)
    target = tmp_path / "xdg"
    monkeypatch.setenv("PIS_DATA_DIR", str(target))

    report = paths.migrate_legacy_data(legacy, move=False)
    assert report["status"] == "MIGRATED"
    assert legacy.exists()
    assert (target / "indexes" / "files.db").is_file()


def test_auto_migration_runs_once(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "checkout" / "data"
    _make_legacy_db(legacy)
    target = tmp_path / "xdg"
    monkeypatch.setenv("PIS_DATA_DIR", str(target))
    monkeypatch.delenv("PIS_NO_AUTO_MIGRATE", raising=False)
    # The explicit PIS_DATA_DIR disables auto-migration by design.
    assert paths.maybe_migrate_legacy_data() is None

    monkeypatch.delenv("PIS_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-home"))
    monkeypatch.setattr(paths, "legacy_data_candidates", _only(legacy))
    report = paths.maybe_migrate_legacy_data()
    assert report is not None and report["status"] == "MOVED"
    assert (tmp_path / "xdg-home" / "pis" / "indexes" / "files.db").is_file()
    # Second call is a no-op because the target DB now exists.
    assert paths.maybe_migrate_legacy_data() is None


def test_auto_migration_respects_opt_out(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "checkout" / "data"
    _make_legacy_db(legacy)
    monkeypatch.delenv("PIS_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-home"))
    monkeypatch.setenv("PIS_NO_AUTO_MIGRATE", "1")
    monkeypatch.setattr(paths, "legacy_data_candidates", _only(legacy))
    assert paths.maybe_migrate_legacy_data() is None
    assert legacy.exists()


def test_cli_reports_resolved_path_in_json_and_stderr(tmp_path: Path, capsys, monkeypatch) -> None:
    import json

    from src.cli import main

    monkeypatch.setenv("PIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PIS_DB_PATH", raising=False)
    assert main(["--json", "status"]) in (0, 2)
    payload = json.loads(capsys.readouterr().out)
    assert payload["_meta"]["db"] == str(tmp_path / "data" / "indexes" / "files.db")
    assert payload["_meta"]["data_dir"] == str(tmp_path / "data")

    assert main(["status"]) in (0, 2)
    captured = capsys.readouterr()
    assert "db:" in captured.err
    assert str(tmp_path / "data" / "indexes" / "files.db") in captured.err


def test_path_preview_does_not_migrate(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "checkout" / "data"
    _make_legacy_db(legacy)
    target = tmp_path / "xdg-home" / "pis"
    monkeypatch.delenv("PIS_DATA_DIR", raising=False)
    monkeypatch.delenv("PIS_DB_PATH", raising=False)
    monkeypatch.delenv("PIS_NO_AUTO_MIGRATE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-home"))
    monkeypatch.setattr(paths, "legacy_data_candidates", _only(legacy))

    preview = paths.resolve_db_path(migrate=False)
    assert str(preview).startswith(str(target))
    # Displaying the path must not move or copy anything.
    assert legacy.exists()
    assert not target.exists()

    # The real resolver performs the migration exactly once.
    assert paths.resolve_db_path() == target / "indexes" / "files.db"
    assert (target / "indexes" / "files.db").is_file()
