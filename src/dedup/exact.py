"""Exact duplicate detection: strong content identity, size-filtered hashing."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from .hashing import HASH_OK, ContentHasher
from .store import DedupStore, _like_prefix


class ExactDuplicateEngine:
    """Exact duplicates = identical SHA-256 content (never name/size/mtime only).

    Hashing is bounded and size-first: only files whose size is shared by another
    candidate are hashed, so unique-size files are never read.
    """

    def __init__(self, db, store: Optional[DedupStore] = None,
                 hasher: Optional[ContentHasher] = None) -> None:
        self.db = db
        self.store = store or DedupStore(db)
        self.hasher = hasher or ContentHasher(db, self.store)

    # -- size candidate groups --------------------------------------------
    def size_candidate_sizes(self, *, min_size: int = 1, max_size: Optional[int] = None,
                             scope_prefix: Optional[str] = None,
                             include_members: bool = True, max_sizes: int = 20000) -> list[int]:
        kinds = ["PHYSICAL_FILE", "ARCHIVE_MEMBER"] if include_members else ["PHYSICAL_FILE"]
        ph = ",".join("?" * len(kinds))
        sql = (f"SELECT f.size_bytes FROM files f WHERE COALESCE(f.state,'ACTIVE')='ACTIVE' "
               f"AND f.document_kind IN ({ph}) AND f.size_bytes >= ?")
        params: list[Any] = [*kinds, int(min_size)]
        if max_size is not None:
            sql += " AND f.size_bytes <= ?"
            params.append(int(max_size))
        if scope_prefix:
            sql += " AND f.path LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(scope_prefix))
        sql += " GROUP BY f.size_bytes HAVING COUNT(*) > 1 ORDER BY f.size_bytes ASC LIMIT ?"
        params.append(int(max_sizes))
        with self.db.get_connection() as conn:
            return [int(r[0]) for r in conn.execute(sql, params).fetchall()]

    def hash_duplicate_candidates(self, *, min_size: int = 1, max_size: Optional[int] = None,
                                  scope_prefix: Optional[str] = None,
                                  include_members: bool = True, max_sizes: int = 20000,
                                  progress: Optional[Callable[[int, int], None]] = None) -> dict[str, Any]:
        """Hash only files that share a size with at least one other candidate."""
        sizes = self.size_candidate_sizes(min_size=min_size, max_size=max_size,
                                          scope_prefix=scope_prefix,
                                          include_members=include_members, max_sizes=max_sizes)
        if not sizes:
            return {"candidate_sizes": 0, "hashed": 0, "ok": 0, "bytes_hashed": 0}
        kinds = ["PHYSICAL_FILE", "ARCHIVE_MEMBER"] if include_members else ["PHYSICAL_FILE"]
        ph = ",".join("?" * len(kinds))
        # Batch the size IN(...) list to stay within SQLite parameter limits.
        stats = {"candidate_sizes": len(sizes), "hashed": 0, "ok": 0,
                 "too_large": 0, "unreadable": 0, "skipped": 0, "bytes_hashed": 0}
        for start in range(0, len(sizes), 500):
            chunk = sizes[start:start + 500]
            sph = ",".join("?" * len(chunk))
            sql = (f"SELECT f.id, f.path, f.size_bytes, f.modified_at, f.document_kind, "
                   f"h.file_id AS h_file, h.size_bytes AS h_size, h.modified_at AS h_mtime "
                   f"FROM files f LEFT JOIN content_hashes h ON h.file_id=f.id "
                   f"WHERE COALESCE(f.state,'ACTIVE')='ACTIVE' AND f.document_kind IN ({ph}) "
                   f"AND f.size_bytes IN ({sph}) AND (h.file_id IS NULL "
                   f"OR h.size_bytes != f.size_bytes OR COALESCE(h.modified_at,'') != COALESCE(f.modified_at,''))")
            params: list[Any] = [*kinds, *chunk]
            if scope_prefix:
                sql += " AND f.path LIKE ? ESCAPE '\\'"
                params.append(_like_prefix(scope_prefix))
            with self.db.get_connection() as conn:
                rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            pending: list[tuple] = []
            for row in rows:
                digest, state, error = self.hasher.hash_one(row, include_members=include_members)
                pending.append((int(row["id"]), "sha256", digest, int(row["size_bytes"] or 0),
                                row.get("modified_at"), state, error))
                if len(pending) >= 500:
                    self.store.set_hashes(pending)
                    pending.clear()
                stats["hashed"] += 1
                if state == HASH_OK:
                    stats["ok"] += 1
                    stats["bytes_hashed"] += int(row["size_bytes"] or 0)
                elif state == "TOO_LARGE":
                    stats["too_large"] += 1
                elif state == "UNREADABLE":
                    stats["unreadable"] += 1
                else:
                    stats["skipped"] += 1
                if progress and stats["hashed"] % 500 == 0:
                    progress(stats["hashed"], stats["hashed"])
            self.store.set_hashes(pending)
        return stats

    # -- groups ------------------------------------------------------------
    def groups(self, **kwargs) -> list[dict[str, Any]]:
        return self.store.exact_duplicate_groups(**kwargs)

    def summary(self, *, min_size: int = 1, scope_prefix: Optional[str] = None,
                include_members: bool = True, include_missing: bool = False) -> dict[str, Any]:
        totals = self.store.duplicate_totals(min_size=min_size, scope_prefix=scope_prefix,
                                             include_members=include_members,
                                             include_missing=include_missing)
        return {**totals, "hash_stats": self.store.hash_stats()}
