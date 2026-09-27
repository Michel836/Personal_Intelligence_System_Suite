"""Maintenance service (M019)."""
from __future__ import annotations

from src.core.database import DatabaseManager
from src.ops.maintenance import MaintenanceService


def _db(tmp_path) -> DatabaseManager:
    db = DatabaseManager(tmp_path / "files.db")
    with db.get_connection() as conn:
        conn.execute("INSERT INTO files (id, path, filename, extension, size_bytes, "
                     "modified_at, state, document_kind, content_extracted) VALUES "
                     "(1, '/c/a.txt', 'a.txt', '.txt', 10, '2024-01-01', 'ACTIVE', "
                     "'PHYSICAL_FILE', 1)")
        conn.commit()
    db.update_content(1, "hello searchable world")
    return db


def test_integrity_and_optimize(tmp_path) -> None:
    svc = MaintenanceService(_db(tmp_path))
    assert svc.integrity_check()["status"] == "OK"
    assert svc.analyze()["status"] == "OK"
    assert svc.optimize()["status"] == "OK"
    assert svc.checkpoint()["status"] == "OK"


def test_vacuum_requires_confirmation_and_precheck(tmp_path) -> None:
    svc = MaintenanceService(_db(tmp_path))
    skipped = svc.vacuum(confirm=False)
    assert skipped["status"] == "SKIPPED" and skipped["details"]["reason"]
    precheck = svc.vacuum_precheck()
    assert set(precheck) >= {"db_size_bytes", "free_bytes", "needed_bytes", "enough_space"}
    done = svc.vacuum(confirm=True)
    assert done["status"] in {"OK", "ERROR"}  # ERROR only if free space genuinely low


def test_fts_consistency_and_rebuild(tmp_path) -> None:
    db = _db(tmp_path)
    svc = MaintenanceService(db)
    assert svc.fts_consistency()["details"]["consistent"] is True
    # Create an unindexed row by disabling the insert trigger first.
    with db.get_connection() as conn:
        conn.execute("DROP TRIGGER IF EXISTS files_fts_insert")
        conn.execute("INSERT INTO files (id, path, filename, extension, size_bytes, "
                     "modified_at, state, document_kind, content_extracted) VALUES "
                     "(2, '/c/b.txt', 'b.txt', '.txt', 10, '2024-01-01', 'ACTIVE', "
                     "'PHYSICAL_FILE', 1)")
        conn.commit()
    desynced = svc.fts_consistency()
    assert desynced["status"] == "WARN" and desynced["details"]["consistent"] is False
    rebuilt = svc.fts_rebuild()
    assert rebuilt["status"] == "OK" and rebuilt["details"]["consistent"] is True


def test_orphan_scan_detects_dangling_reference(tmp_path) -> None:
    db = _db(tmp_path)
    from src.dedup import DedupStore
    store = DedupStore(db)
    store.set_hash(999, digest="deadbeef", size_bytes=1, modified_at="2024-01-01")
    result = MaintenanceService(db).orphan_scan()
    assert result["status"] == "WARN"
    assert result["details"]["orphans"].get("content_hashes", 0) >= 1


def test_schema_init_sets_user_version(tmp_path) -> None:
    db = _db(tmp_path)
    result = MaintenanceService(db).schema_init()
    assert result["status"] == "OK" and result["details"]["user_version"] >= 1
    with db.get_connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 1


def test_semantic_consistency_without_store(tmp_path) -> None:
    result = MaintenanceService(_db(tmp_path)).semantic_consistency()
    assert result["status"] == "OK"
    assert result["details"]["consistent"] is True


def test_dispatcher_reports_unknown_operation(tmp_path) -> None:
    svc = MaintenanceService(_db(tmp_path))
    assert svc.run("does-not-exist")["status"] == "ERROR"
    assert "integrity" in svc.operations()
