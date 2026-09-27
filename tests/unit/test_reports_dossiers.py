"""Dossier static/dynamic membership, snapshot and integrity (M018)."""
from __future__ import annotations

from src.core.database import DatabaseManager
from src.reports.dossiers import DossierService, run_query
from src.reports.models import DossierMode


def _add_doc(db: DatabaseManager, file_id: int, name: str, text: str, *,
             state: str = "ACTIVE", path: str | None = None) -> None:
    p = path or f"/corpus/{name}"
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
            "state, document_kind, content_extracted) VALUES (?, ?, ?, '.txt', 10, "
            "'2024-01-01 00:00:00', ?, 'PHYSICAL_FILE', 1)",
            (file_id, p, name, state))
        conn.commit()
    db.update_content(file_id, text)


def test_static_dossier_keeps_order_and_manual_membership(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add_doc(db, 1, "a.txt", "alpha content")
    _add_doc(db, 2, "b.txt", "beta content")
    _add_doc(db, 3, "c.txt", "gamma content")
    svc = DossierService(db)
    d = svc.create("Static one", mode=DossierMode.STATIC.value, file_ids=[3, 1])
    assert d["mode"] == DossierMode.STATIC.value
    resolved = svc.resolve(d["dossier_id"])
    assert [m["file_id"] for m in resolved["members"]] == [3, 1]
    # Reorder
    svc.reorder(d["dossier_id"], [1, 3])
    assert [m["file_id"] for m in svc.resolve(d["dossier_id"])["members"]] == [1, 3]


def test_dynamic_dossier_query_and_manual_override(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add_doc(db, 1, "alpha.txt", "alpha project notes")
    _add_doc(db, 2, "beta.txt", "beta project notes")
    _add_doc(db, 3, "other.txt", "unrelated text")
    svc = DossierService(db)
    d = svc.create("Dynamic", mode=DossierMode.DYNAMIC.value, query={"query": "project"})
    assert {m["file_id"] for m in svc.resolve(d["dossier_id"])["members"]} == {1, 2}
    # Manual membership wins: pin doc 3 although the query does not match it.
    svc.add_documents(d["dossier_id"], [3])
    resolved = svc.resolve(d["dossier_id"])
    assert {m["file_id"] for m in resolved["members"]} == {1, 2, 3}
    manual = next(m for m in resolved["members"] if m["file_id"] == 3)
    assert manual["source"] == "manual"
    # Manual exclusion wins: pin doc 1 out.
    svc.exclude_documents(d["dossier_id"], [1])
    assert {m["file_id"] for m in svc.resolve(d["dossier_id"])["members"]} == {2, 3}


def test_freeze_snapshot_and_compare(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add_doc(db, 1, "alpha.txt", "shared project token")
    _add_doc(db, 2, "beta.txt", "shared project token")
    svc = DossierService(db)
    d = svc.create("Dyn", mode=DossierMode.DYNAMIC.value, query={"query": "project"})
    frozen = svc.freeze(d["dossier_id"])
    assert frozen["frozen_count"] == 2
    # A new match appears after the snapshot.
    _add_doc(db, 3, "gamma.txt", "another project token")
    diff = svc.compare_snapshot(d["dossier_id"])
    assert diff["has_snapshot"] and diff["added"] == [3] and diff["removed"] == []
    # A member leaves the query after the snapshot.
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=2")
        conn.commit()
    diff2 = svc.compare_snapshot(d["dossier_id"])
    assert 2 in diff2["removed"]
    resolved = svc.resolve(d["dossier_id"])
    assert resolved["missing"] == 0  # MISSING excluded from ACTIVE-only search
    svc.unfreeze(d["dossier_id"])
    assert svc.compare_snapshot(d["dossier_id"])["has_snapshot"] is False


def test_static_not_silently_changed_by_query(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add_doc(db, 1, "alpha.txt", "shared project token")
    _add_doc(db, 2, "beta.txt", "shared project token")
    svc = DossierService(db)
    d = svc.create("Static", mode=DossierMode.STATIC.value, file_ids=[1])
    # Attach a query but keep STATIC mode: membership must not silently grow.
    svc.store.set_dossier_mode(d["dossier_id"], DossierMode.STATIC.value, {"query": "project"})
    assert [m["file_id"] for m in svc.resolve(d["dossier_id"])["members"]] == [1]


def test_missing_and_renamed_source(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add_doc(db, 1, "alpha.txt", "alpha")
    svc = DossierService(db)
    d = svc.create("Static", mode=DossierMode.STATIC.value, file_ids=[1])
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=1")
        conn.commit()
    resolved = svc.resolve(d["dossier_id"])
    assert resolved["missing"] == 1
    assert resolved["members"][0]["missing"] is True
    # Rename: id is stable, path changes, membership intact.
    with db.get_connection() as conn:
        conn.execute("UPDATE files SET state='ACTIVE', path='/corpus/renamed.txt', "
                     "filename='renamed.txt' WHERE id=1")
        conn.commit()
    resolved = svc.resolve(d["dossier_id"])
    assert resolved["members"][0]["file_id"] == 1
    assert resolved["members"][0]["filename"] == "renamed.txt"


def test_saved_query_change_is_reflected(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add_doc(db, 1, "alpha.txt", "alpha token")
    _add_doc(db, 2, "beta.txt", "beta token")
    svc = DossierService(db)
    d = svc.create("Dyn", mode=DossierMode.DYNAMIC.value, query={"query": "alpha"})
    assert {m["file_id"] for m in svc.resolve(d["dossier_id"])["members"]} == {1}
    svc.store.set_dossier_mode(d["dossier_id"], DossierMode.DYNAMIC.value, {"query": "beta"})
    assert {m["file_id"] for m in svc.resolve(d["dossier_id"])["members"]} == {2}


def test_run_query_reuses_canonical_search(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add_doc(db, 1, "alpha.txt", "alpha project")
    _add_doc(db, 2, "noise.txt", "nothing here")
    rows = run_query(db, {"query": "project", "extension": ".txt", "limit": 10})
    assert [r["id"] for r in rows] == [1]
