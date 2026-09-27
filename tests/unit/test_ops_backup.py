"""Backup / restore: consistency, manifest and hostile cases (M019)."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
from pathlib import Path

from src.core.database import DatabaseManager
from src.ops.backup import (
    BACKUP_SCHEMA,
    create_backup,
    restore_backup,
    verify_backup,
)


def _db(tmp_path) -> DatabaseManager:
    db = DatabaseManager(tmp_path / "files.db")
    with db.get_connection() as conn:
        for i in (1, 2):
            conn.execute(
                "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
                "state, document_kind, content_extracted) VALUES (?, ?, ?, '.txt', 10, "
                "'2024-01-01', 'ACTIVE', 'PHYSICAL_FILE', 1)",
                (i, f"/c/{i}.txt", f"{i}.txt"))
        conn.commit()
    db.update_content(1, "backup token one")
    return db


def _manifest(**overrides) -> dict:
    manifest = {
        "schema": BACKUP_SCHEMA,
        "backup_id": "bk_test",
        "created_at": "2024-01-01 00:00:00",
        "app_version": {"app": "1.0.0"},
        "db_schema_version": {"fts_schema_version": "1", "expected_fts_schema_version": "1"},
        "components": {"db": {"member": "db/files.db", "bytes": 0, "sha256": ""},
                       "semantic": [], "config": {"member": "config/effective_config.json"}},
        "included": ["sqlite-db"], "excluded": ["source-corpus", "secrets"],
        "privacy_note": "x", "warnings": [],
    }
    manifest.update(overrides)
    return manifest


def _craft(tmp_path: Path, members: dict[str, bytes], manifest: dict) -> Path:
    path = tmp_path / "crafted.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in {**members, "manifest.json": json.dumps(manifest).encode()}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


# --- happy path --------------------------------------------------------------
def test_backup_create_verify_and_restore(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_BACKUP_DIR", str(tmp_path / "backups"))
    db = _db(tmp_path)
    result = create_backup(db)
    assert Path(result.archive_path).is_file()
    assert result.manifest["components"]["db"]["sha256"]
    assert result.manifest["excluded"]  # source corpus documented as excluded

    verified = verify_backup(result.archive_path)
    assert verified["ok"] is True and verified["schema_compatible"] is True

    target = tmp_path / "restored" / "files.db"
    restored = restore_backup(result.archive_path, target_db=target, confirm=True)
    assert restored.status == "RESTORED" and restored.integrity == "ok"
    conn = sqlite3.connect(str(target))
    try:
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 2
    finally:
        conn.close()


def test_restore_requires_confirmation_and_refuses_existing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_BACKUP_DIR", str(tmp_path / "backups"))
    db = _db(tmp_path)
    archive = create_backup(db).archive_path
    assert restore_backup(archive, target_db=tmp_path / "n.db").status == "REFUSED"
    target = tmp_path / "restored.db"
    target.write_text("existing")
    refused = restore_backup(archive, target_db=target, confirm=True)
    assert refused.status == "REFUSED" and "exists" in (refused.error or "")
    forced = restore_backup(archive, target_db=target, confirm=True, force=True)
    assert forced.status == "RESTORED" and forced.rollback_path
    assert Path(forced.rollback_path).is_file()


def test_backup_copies_semantic_store_but_no_secrets(tmp_path, monkeypatch) -> None:
    store = tmp_path / "embeddings" / "model-x"
    store.mkdir(parents=True)
    (store / "meta.json").write_text(json.dumps({"model_key": "model-x", "dim": 4, "count": 3}))
    (store / "matrix.npy").write_bytes(b"\x00" * 64)
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(tmp_path / "embeddings"))
    monkeypatch.setenv("PIS_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("PIS_API_KEY", "topsecret-backup")
    db = _db(tmp_path)
    result = create_backup(db)
    assert any(c["model_key"] == "model-x" for c in result.manifest["components"]["semantic"])
    with tarfile.open(result.archive_path, "r:gz") as tar:
        config = tar.extractfile("config/effective_config.json").read().decode()
    assert "topsecret-backup" not in config
    assert "***set***" in config


# --- hostile cases -----------------------------------------------------------
def test_truncated_backup_is_refused(tmp_path) -> None:
    path = tmp_path / "trunc.tar.gz"
    path.write_bytes(b"\x1f\x8b\x08\x00broken")
    result = verify_backup(path)
    assert result["ok"] is False


def test_checksum_mismatch_is_detected(tmp_path) -> None:
    manifest = _manifest()
    manifest["components"]["db"]["sha256"] = "0" * 64
    path = _craft(tmp_path, {"db/files.db": b"not-really-a-db"}, manifest)
    result = verify_backup(path)
    assert result["ok"] is False
    assert any("checksum" in p for p in result["problems"])


def test_path_traversal_member_is_rejected(tmp_path) -> None:
    manifest = _manifest()
    manifest["components"]["db"]["sha256"] = hashlib.sha256(b"x").hexdigest()
    path = _craft(tmp_path, {"db/files.db": b"x", "../evil.txt": b"boom"}, manifest)
    result = verify_backup(path)
    assert result["ok"] is False
    assert result.get("problems")


def test_incompatible_schema_is_flagged(tmp_path) -> None:
    manifest = _manifest(db_schema_version={"expected_fts_schema_version": "999"})
    manifest["components"]["db"]["sha256"] = hashlib.sha256(b"x").hexdigest()
    path = _craft(tmp_path, {"db/files.db": b"x"}, manifest)
    result = verify_backup(path)
    assert result["ok"] is False and result["schema_compatible"] is False


def test_corrupt_sqlite_in_backup_is_refused_at_staging(tmp_path) -> None:
    payload = b"this is not a sqlite database"
    manifest = _manifest()
    manifest["components"]["db"]["sha256"] = hashlib.sha256(payload).hexdigest()
    path = _craft(tmp_path, {"db/files.db": payload}, manifest)
    assert verify_backup(path)["ok"] is True  # checksum is internally consistent
    result = restore_backup(path, target_db=tmp_path / "out.db", confirm=True)
    assert result.status == "REFUSED" and "unreadable" in (result.error or "")


def test_missing_db_member_is_detected(tmp_path) -> None:
    manifest = _manifest()
    path = _craft(tmp_path, {}, manifest)
    result = verify_backup(path)
    assert result["ok"] is False
