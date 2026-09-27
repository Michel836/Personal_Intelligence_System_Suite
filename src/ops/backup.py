"""Application-consistent backup & conservative restore (M019, phases 14-17).

Design:

* The canonical SQLite database is snapshotted with the **SQLite backup API**,
  which is consistent under WAL and does not require stopping the app.
* The semantic matrix store is copied file-by-file (bounded).
* A redacted config snapshot is included; **secrets are never copied**.
* The source corpus is never included or modified.
* Restore validates the manifest and every checksum, checks schema
  compatibility, extracts to a **staging** directory, runs ``integrity_check``,
  and only then replaces the target — keeping a ``.pre-restore`` rollback copy
  and refusing to overwrite silently.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from .config import effective_config
from .schema import APP_SCHEMA_VERSION, db_schema_version
from .version import app_version

BACKUP_SCHEMA = "pis-backup/v1"
_MANIFEST_NAME = "manifest.json"
_DB_MEMBER = "db/files.db"
_CONFIG_MEMBER = "config/effective_config.json"
_SEMANTIC_PREFIX = "semantic/"

_DEFAULT_MAX_SEMANTIC_MB = int(os.environ.get("PIS_BACKUP_MAX_SEMANTIC_MB", "8192"))


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _sha256(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_dir() -> Path:
    return Path(os.environ.get("PIS_BACKUP_DIR")
                or (Path.home() / ".pis-backups")).expanduser()


def _semantic_base_dir() -> Path:
    raw = os.environ.get("PIS_EMBEDDING_STORE_DIR") or "data/cache/embeddings"
    path = Path(raw)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


@dataclass
class BackupResult:
    backup_id: str
    archive_path: str
    manifest_path: str
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"backup_id": self.backup_id, "archive_path": self.archive_path,
                "manifest_path": self.manifest_path, "manifest": self.manifest,
                "warnings": list(self.warnings), "duration_s": self.duration_s}


@dataclass
class RestoreResult:
    status: str
    backup_id: str | None = None
    target_db: str | None = None
    rollback_path: str | None = None
    restored: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    integrity: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "backup_id": self.backup_id,
                "target_db": self.target_db, "rollback_path": self.rollback_path,
                "restored": list(self.restored), "warnings": list(self.warnings),
                "error": self.error, "integrity": self.integrity}


# --- creation ----------------------------------------------------------------
def _snapshot_sqlite(db_path: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _semantic_components(base: Path, staging: Path, warnings: list[str]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    if not base.is_dir():
        return components
    total = 0
    cap = _DEFAULT_MAX_SEMANTIC_MB * 1024 * 1024
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        dest_dir = staging / _SEMANTIC_PREFIX / child.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in ("meta.json", "matrix.npy", "ids.npy", "hashes.npy"):
            src_file = child / name
            if not src_file.is_file():
                continue
            size = src_file.stat().st_size
            if total + size > cap:
                warnings.append(f"semantic store exceeds {_DEFAULT_MAX_SEMANTIC_MB} MB; truncated")
                break
            shutil.copy2(src_file, dest_dir / name)
            total += size
            components.append({"member": f"{_SEMANTIC_PREFIX}{child.name}/{name}",
                               "model_key": child.name, "bytes": size,
                               "sha256": _sha256(src_file)})
    return components


def create_backup(db: Any, *, out_dir: Path | str | None = None,
                  include_semantic: bool = True) -> BackupResult:
    warnings: list[str] = []
    t0 = time.perf_counter()
    db_path = Path(db.db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")
    target_dir = Path(out_dir) if out_dir else _backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_id = f"bk_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"

    with tempfile.TemporaryDirectory(prefix="pis-backup-") as tmp:
        staging = Path(tmp)
        snapshot = staging / _DB_MEMBER
        _snapshot_sqlite(db_path, snapshot)

        config = effective_config(include_paths=False)
        config_path = staging / _CONFIG_MEMBER
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

        semantic: list[dict[str, Any]] = []
        if include_semantic:
            semantic = _semantic_components(_semantic_base_dir(), staging, warnings)

        schema = db_schema_version(db)
        manifest: dict[str, Any] = {
            "schema": BACKUP_SCHEMA,
            "backup_id": backup_id,
            "created_at": _now(),
            "app_version": app_version(),
            "db_schema_version": schema,
            "components": {
                "db": {"member": _DB_MEMBER, "bytes": snapshot.stat().st_size,
                       "sha256": _sha256(snapshot), "source_name": db_path.name},
                "semantic": semantic,
                "config": {"member": _CONFIG_MEMBER,
                           "sha256": _sha256(config_path)},
            },
            "included": ["sqlite-db", "config(redacted)"] + (["semantic-store"] if semantic else []),
            "excluded": ["source-corpus", "secrets", "extracted-report-artifacts"],
            "privacy_note": "Config snapshot is secret-redacted; source corpus is never copied.",
            "warnings": warnings,
        }
        (staging / _MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        archive_path = target_dir / f"{backup_id}.tar.gz"
        tmp_archive = target_dir / f".{backup_id}.tar.gz.tmp"
        with tarfile.open(tmp_archive, "w:gz") as tar:
            for member in (_MANIFEST_NAME, _DB_MEMBER, _CONFIG_MEMBER):
                tar.add(staging / member, arcname=member)
            for comp in semantic:
                arc = comp["member"]
                tar.add(staging / arc, arcname=arc)
        os.replace(tmp_archive, archive_path)

    manifest_path = target_dir / f"{backup_id}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    duration = round(time.perf_counter() - t0, 3)
    logger.info(f"M019 backup {backup_id} created ({archive_path.stat().st_size} bytes) in {duration}s")
    return BackupResult(backup_id=backup_id, archive_path=str(archive_path),
                        manifest_path=str(manifest_path), manifest=manifest,
                        warnings=warnings, duration_s=duration)


# --- verification ------------------------------------------------------------
def _safe_members(tar: tarfile.TarFile) -> list[str]:
    problems: list[str] = []
    for m in tar.getmembers():
        name = m.name
        if m.issym() or m.islnk() or m.isdev():
            problems.append(f"unsafe member type: {name}")
            continue
        if name.startswith(("/", "\\")) or ".." in Path(name).parts:
            problems.append(f"unsafe path: {name}")
    return problems


def _member_bytes(tar: tarfile.TarFile, name: str) -> bytes:
    handle = tar.extractfile(name)
    if handle is None:
        raise ValueError(f"not a regular file: {name}")
    return handle.read()


def verify_backup(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "error": "backup file not found"}
    try:
        with tarfile.open(path, "r:gz") as tar:
            unsafe = _safe_members(tar)
            if unsafe:
                return {"ok": False, "error": "unsafe archive", "problems": unsafe}
            names = tar.getnames()
            if _MANIFEST_NAME not in names:
                return {"ok": False, "error": "manifest missing from archive"}
            manifest = json.loads(_member_bytes(tar, _MANIFEST_NAME).decode("utf-8"))
            if manifest.get("schema") != BACKUP_SCHEMA:
                return {"ok": False, "error": f"unexpected manifest schema: {manifest.get('schema')}"}
            problems: list[str] = []
            db_comp = manifest.get("components", {}).get("db", {})
            if db_comp.get("member") not in names:
                problems.append("db member missing")
            else:
                digest = hashlib.sha256(_member_bytes(tar, db_comp["member"])).hexdigest()
                if digest != db_comp.get("sha256"):
                    problems.append("db checksum mismatch")
            for comp in manifest.get("components", {}).get("semantic", []):
                member = comp.get("member")
                if member not in names:
                    problems.append(f"semantic member missing: {member}")
                    continue
                digest = hashlib.sha256(_member_bytes(tar, member)).hexdigest()
                if digest != comp.get("sha256"):
                    problems.append(f"semantic checksum mismatch: {member}")
            expected_schema = manifest.get("db_schema_version", {}).get("expected_fts_schema_version")
            compatible = expected_schema in (None, APP_SCHEMA_VERSION)
            if not compatible:
                problems.append(f"incompatible schema: {expected_schema}")
            return {"ok": not problems, "problems": problems, "manifest": manifest,
                    "schema_compatible": compatible}
    except (tarfile.TarError, OSError, ValueError, EOFError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"unreadable backup: {type(exc).__name__}"}


# --- restore -----------------------------------------------------------------
def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for m in tar.getmembers():
        if m.issym() or m.islnk() or m.isdev():
            raise ValueError(f"unsafe member: {m.name}")
        target = (dest / m.name).resolve()
        if target != dest and dest not in target.parents:
            raise ValueError(f"path traversal in archive: {m.name}")
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not m.isfile():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(m)
        if source is None:
            continue
        with target.open("wb") as fh:
            shutil.copyfileobj(source, fh)


def restore_backup(path: Path | str, *, target_db: Path | str | None = None,
                   restore_semantic: bool = False, force: bool = False,
                   confirm: bool = False, semantic_target: Path | str | None = None) -> RestoreResult:
    verification = verify_backup(path)
    if not verification.get("ok"):
        return RestoreResult(status="REFUSED", error=verification.get("error")
                             or "; ".join(verification.get("problems", [])))
    if not confirm:
        return RestoreResult(status="REFUSED",
                             error="confirmation required (pass confirm=True)")
    manifest = verification["manifest"]
    backup_id = manifest.get("backup_id")
    target = Path(target_db) if target_db else Path("data/indexes/files.db")
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pis-restore-") as tmp:
        staging = Path(tmp)
        try:
            with tarfile.open(Path(path), "r:gz") as tar:
                _safe_extract(tar, staging)
        except (tarfile.TarError, OSError, ValueError, EOFError) as exc:
            return RestoreResult(status="REFUSED", backup_id=backup_id,
                                 error=f"extraction failed: {type(exc).__name__}")
        staged_db = staging / _DB_MEMBER
        if not staged_db.is_file():
            return RestoreResult(status="REFUSED", backup_id=backup_id,
                                 error="staged database missing")
        # Verify staged integrity before touching the target.
        try:
            conn = sqlite3.connect(str(staged_db))
            try:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            return RestoreResult(status="REFUSED", backup_id=backup_id,
                                 error=f"staged database unreadable: {type(exc).__name__}")
        if result != "ok":
            return RestoreResult(status="REFUSED", backup_id=backup_id, integrity=str(result),
                                 error="staged integrity check failed")
        if target.exists() and not force:
            return RestoreResult(status="REFUSED", backup_id=backup_id, target_db=str(target),
                                 error="target exists; pass force=True to replace (rollback copy kept)")

        target.parent.mkdir(parents=True, exist_ok=True)
        rollback: Path | None = None
        if target.exists():
            rollback = target.with_name(target.name + f".pre-restore.{int(time.time())}")
            shutil.copy2(target, rollback)
        tmp_target = target.with_name(target.name + f".restore-{uuid.uuid4().hex[:6]}")
        shutil.copy2(staged_db, tmp_target)
        os.replace(tmp_target, target)

        restored = ["db"]
        if restore_semantic:
            base = Path(semantic_target) if semantic_target else _semantic_base_dir()
            base.mkdir(parents=True, exist_ok=True)
            for comp in manifest.get("components", {}).get("semantic", []):
                member = comp["member"]
                rel = Path(member).relative_to(_SEMANTIC_PREFIX)
                dest = base / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staging / member, dest)
            restored.append("semantic")
        logger.info(f"M019 restore {backup_id} -> {target} (rollback={rollback})")
        return RestoreResult(status="RESTORED", backup_id=backup_id, target_db=str(target),
                             rollback_path=str(rollback) if rollback else None,
                             restored=restored, warnings=warnings, integrity="ok")
