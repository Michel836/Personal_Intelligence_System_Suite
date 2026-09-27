"""Bounded, incremental content hashing (SHA-256) for exact duplicates."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from .store import DedupStore

HASH_OK = "OK"
HASH_SKIPPED = "SKIPPED"
HASH_TOO_LARGE = "TOO_LARGE"
HASH_UNREADABLE = "UNREADABLE"

_CHUNK = 1024 * 1024


class ContentHasher:
    """Compute and persist strong content identity, incrementally.

    Files larger than ``max_bytes`` are recorded as ``TOO_LARGE`` (deterministic
    and not retried unnecessarily); unreadable files as ``UNREADABLE`` (retried on
    a later backfill). Archive members are hashed only when ``include_members`` is
    requested, because that requires re-reading the parent container.
    """

    def __init__(self, db: Any, store: DedupStore | None = None, *,
                 max_bytes: int = 1024 * 1024 * 1024, chunk: int = _CHUNK) -> None:
        self.db = db
        self.store = store or DedupStore(db)
        self.max_bytes = int(max_bytes)
        self.chunk = int(chunk)

    # -- single file -------------------------------------------------------
    @staticmethod
    def hash_stream(fh: Any) -> str:
        h = hashlib.sha256()
        while True:
            block = fh.read(_CHUNK)
            if not block:
                break
            h.update(block)
        return h.hexdigest()

    def _hash_filesystem(self, path: str, size: int) -> tuple[str | None, str, str | None]:
        if size > self.max_bytes:
            return None, HASH_TOO_LARGE, f"size {size} > max {self.max_bytes}"
        try:
            with open(path, "rb") as fh:
                return self.hash_stream(fh), HASH_OK, None
        except (OSError, PermissionError) as exc:
            return None, HASH_UNREADABLE, type(exc).__name__

    def _archive_member_bytes(self, row: dict[str, Any]) -> tuple[str | None, str, str | None]:
        from ..archives.inspector import (
            ArchiveInspector,
            ArchiveLimitError,
            ArchiveMember,
            MemberType,
        )

        with self.db.get_connection() as conn:
            parent = conn.execute(
                "SELECT id, path FROM files WHERE id=?", (int(row.get("archive_parent_id") or -1),)
            ).fetchone()
            member = conn.execute(
                "SELECT archive_member_path, member_uncompressed_size, "
                "member_compressed_size, member_crc, member_type FROM files WHERE id=?",
                (int(row["id"]),),
            ).fetchone()
        if parent is None or member is None:
            return None, HASH_UNREADABLE, "missing parent/member"
        if int(member["member_uncompressed_size"] or 0) > self.max_bytes:
            return None, HASH_TOO_LARGE, "member too large"
        try:
            inspector = ArchiveInspector(parent["path"])
            m = ArchiveMember(
                member_path=member["archive_member_path"],
                raw_name=member["archive_member_path"],
                member_type=MemberType(member["member_type"] or "FILE"),
                uncompressed_size=int(member["member_uncompressed_size"] or 0),
                compressed_size=int(member["member_compressed_size"] or 0),
                crc=member["member_crc"],
            )
            data = inspector.open_member(m).read()
            return hashlib.sha256(data).hexdigest(), HASH_OK, None
        except ArchiveLimitError as exc:
            return None, HASH_SKIPPED, f"limit:{exc}"
        except Exception as exc:  # noqa: BLE001 - one bad member must not stop the pass
            return None, HASH_UNREADABLE, type(exc).__name__

    def hash_one(self, row: dict[str, Any], *, include_members: bool) -> tuple[str | None, str, str | None]:
        if row.get("document_kind") == "ARCHIVE_MEMBER":
            if not include_members:
                return None, HASH_SKIPPED, "members disabled"
            return self._archive_member_bytes(row)
        return self._hash_filesystem(row["path"], int(row.get("size_bytes") or 0))

    # -- bounded backfill --------------------------------------------------
    def backfill(self, *, min_size: int = 1, max_size: int | None = None,
                 scope_prefix: str | None = None, include_members: bool = False,
                 limit: int | None = None,
                 progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        targets = self.store.stale_hash_targets(
            min_size=min_size, max_size=max_size, scope_prefix=scope_prefix,
            include_members=include_members, limit=limit,
        )
        stats: dict[str, Any] = {
            "candidates": len(targets), "hashed": 0, "ok": 0,
            "too_large": 0, "unreadable": 0, "skipped": 0, "bytes_hashed": 0,
            "errors": [],
        }
        t0 = time.perf_counter()
        pending: list[tuple[Any, ...]] = []
        for i, row in enumerate(targets):
            digest, state, error = self.hash_one(row, include_members=include_members)
            pending.append((int(row["id"]), "sha256", digest, int(row.get("size_bytes") or 0),
                            row.get("modified_at"), state, error))
            if len(pending) >= 500:
                self.store.set_hashes(pending)
                pending.clear()
            stats["hashed"] += 1
            if state == HASH_OK:
                stats["ok"] += 1
                stats["bytes_hashed"] += int(row.get("size_bytes") or 0)
            elif state == HASH_TOO_LARGE:
                stats["too_large"] += 1
            elif state == HASH_UNREADABLE:
                stats["unreadable"] += 1
                if len(stats["errors"]) < 20:
                    stats["errors"].append({"id": row["id"], "error": error})
            else:
                stats["skipped"] += 1
            if progress and (i + 1) % 500 == 0:
                progress(i + 1, len(targets))
        self.store.set_hashes(pending)
        wall = time.perf_counter() - t0
        stats["wall_s"] = round(wall, 3)
        stats["files_per_sec"] = round(stats["hashed"] / wall, 1) if wall else 0
        stats["mb_per_sec"] = round((stats["bytes_hashed"] / 1e6) / wall, 1) if wall else 0
        logger.info(f"hash backfill: {stats}")
        return stats

    def prune_orphan_hashes(self) -> int:
        with self.db.get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM content_hashes WHERE file_id NOT IN (SELECT id FROM files)"
            )
            conn.commit()
            return int(cur.rowcount or 0)
