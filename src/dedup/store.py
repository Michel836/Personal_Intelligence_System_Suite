"""Persistent dedup/version/related metadata in the canonical SQLite database.

All tables are additive and live in the same database as ``files`` so the
lifecycle, FTS and semantic layers keep a single source of truth. Nothing here
stores file content or private paths in artifacts; only the app database.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Optional


class DedupStore:
    """Schema + CRUD for content hashes, version families and near-dup edges."""

    def __init__(self, db) -> None:  # db: DatabaseManager
        self.db = db
        self._ensure()

    # -- schema ------------------------------------------------------------
    def _ensure(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS content_hashes (
                    file_id INTEGER PRIMARY KEY,
                    algorithm TEXT NOT NULL DEFAULT 'sha256',
                    digest TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    modified_at TEXT,
                    state TEXT NOT NULL DEFAULT 'OK',
                    error TEXT,
                    hashed_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hashes_digest "
                         "ON content_hashes(algorithm, digest)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hashes_size "
                         "ON content_hashes(size_bytes)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hashes_state "
                         "ON content_hashes(state)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS version_families (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_key TEXT UNIQUE NOT NULL,
                    base_name TEXT,
                    directory TEXT,
                    confidence TEXT NOT NULL DEFAULT 'UNORDERED',
                    evidence TEXT,
                    member_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS version_members (
                    family_id INTEGER NOT NULL,
                    file_id INTEGER NOT NULL,
                    rank INTEGER,
                    confidence TEXT,
                    evidence TEXT,
                    is_primary INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (family_id, file_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_version_members_file "
                         "ON version_members(file_id)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS near_duplicate_edges (
                    src_id INTEGER NOT NULL,
                    dst_id INTEGER NOT NULL,
                    semantic_score REAL,
                    lexical_score REAL,
                    reason TEXT,
                    algorithm TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (src_id, dst_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_near_dup_dst "
                         "ON near_duplicate_edges(dst_id)")
            conn.commit()

    # -- content hashes ----------------------------------------------------
    def set_hash(self, file_id: int, *, digest: Optional[str], size_bytes: int,
                 modified_at: Optional[str], state: str = "OK",
                 error: Optional[str] = None, algorithm: str = "sha256") -> None:
        self.set_hashes([(int(file_id), algorithm, digest, int(size_bytes), modified_at, state, error)])

    def set_hashes(self, rows: Iterable[tuple]) -> None:
        """Batch-upsert ``(file_id, algorithm, digest, size, modified_at, state, error)``."""
        rows = list(rows)
        if not rows:
            return
        with self.db.get_connection() as conn:
            conn.executemany(
                """INSERT INTO content_hashes
                       (file_id, algorithm, digest, size_bytes, modified_at, state, error, hashed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(file_id) DO UPDATE SET
                       algorithm = excluded.algorithm, digest = excluded.digest,
                       size_bytes = excluded.size_bytes, modified_at = excluded.modified_at,
                       state = excluded.state, error = excluded.error,
                       hashed_at = CURRENT_TIMESTAMP""",
                rows,
            )
            conn.commit()

    def get_hash(self, file_id: int) -> Optional[dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM content_hashes WHERE file_id=?", (int(file_id),)
            ).fetchone()
        return dict(row) if row else None

    def hash_stats(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'").fetchone()[0]
            by_state = dict(conn.execute(
                "SELECT state, COUNT(*) FROM content_hashes GROUP BY state").fetchall())
            distinct = conn.execute(
                "SELECT COUNT(DISTINCT digest) FROM content_hashes WHERE state='OK' AND digest IS NOT NULL"
            ).fetchone()[0]
        hashed = sum(by_state.values())
        return {"active_files": int(total), "hash_rows": hashed,
                "by_state": by_state, "distinct_digests": int(distinct),
                "coverage": round(hashed / total, 4) if total else 0.0}

    def stale_hash_targets(self, *, min_size: int = 1, max_size: Optional[int] = None,
                           scope_prefix: Optional[str] = None, include_members: bool = False,
                           limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Files whose stored hash is missing or invalidated by size/mtime change."""
        kinds = ["PHYSICAL_FILE", "ARCHIVE_MEMBER"] if include_members else ["PHYSICAL_FILE"]
        placeholders = ",".join("?" * len(kinds))
        sql = f"""
            SELECT f.id, f.path, f.size_bytes, f.modified_at, f.document_kind,
                   h.size_bytes AS h_size, h.modified_at AS h_mtime, h.state AS h_state
            FROM files f LEFT JOIN content_hashes h ON h.file_id = f.id
            WHERE COALESCE(f.state,'ACTIVE')='ACTIVE'
              AND f.document_kind IN ({placeholders})
              AND f.size_bytes >= ?
              AND (h.file_id IS NULL
                   OR h.size_bytes != f.size_bytes
                   OR COALESCE(h.modified_at,'') != COALESCE(f.modified_at,'')
                   OR h.state IN ('UNREADABLE'))
        """
        params: list[Any] = [*kinds, int(min_size)]
        if max_size is not None:
            sql += " AND f.size_bytes <= ?"
            params.append(int(max_size))
        if scope_prefix:
            sql += " AND f.path LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(scope_prefix))
        sql += " ORDER BY f.size_bytes ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # -- exact duplicate groups -------------------------------------------
    def exact_duplicate_groups(self, *, min_size: int = 1, scope_prefix: Optional[str] = None,
                               include_members: bool = True, include_missing: bool = False,
                               max_groups: int = 500,
                               max_members_per_group: int = 100) -> list[dict[str, Any]]:
        """Group ACTIVE files by identical strong content hash (size pre-filtered)."""
        kinds = ["PHYSICAL_FILE", "ARCHIVE_MEMBER"] if include_members else ["PHYSICAL_FILE"]
        placeholders = ",".join("?" * len(kinds))
        sql = f"""
            SELECT h.digest AS digest,
                   COUNT(*) AS n,
                   MIN(f.size_bytes) AS size_bytes,
                   SUM(f.size_bytes) AS total_bytes
            FROM content_hashes h JOIN files f ON f.id = h.file_id
            WHERE h.state='OK' AND h.digest IS NOT NULL
              AND f.document_kind IN ({placeholders})
              AND f.size_bytes >= ?
        """
        params: list[Any] = [*kinds, int(min_size)]
        if not include_missing:
            sql += " AND COALESCE(f.state,'ACTIVE')='ACTIVE'"
        if scope_prefix:
            sql += " AND f.path LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(scope_prefix))
        sql += " GROUP BY h.digest HAVING COUNT(*) > 1"
        sql += " ORDER BY (COUNT(*)-1) * MIN(f.size_bytes) DESC LIMIT ?"
        params.append(int(max_groups))
        with self.db.get_connection() as conn:
            groups = [dict(r) for r in conn.execute(sql, params).fetchall()]
            for g in groups:
                members_sql = f"""
                    SELECT f.id, f.path, f.filename, f.size_bytes, f.document_kind,
                           COALESCE(f.state,'ACTIVE') AS state, f.archive_parent_id,
                           f.modified_at
                    FROM content_hashes h JOIN files f ON f.id = h.file_id
                    WHERE h.state='OK' AND h.digest=?
                      AND f.document_kind IN ({placeholders})
                """
                mparams: list[Any] = [g["digest"], *kinds]
                if not include_missing:
                    members_sql += " AND COALESCE(f.state,'ACTIVE')='ACTIVE'"
                if scope_prefix:
                    members_sql += " AND f.path LIKE ? ESCAPE '\\'"
                    mparams.append(_like_prefix(scope_prefix))
                members_sql += " ORDER BY f.path ASC"
                if max_members_per_group and max_members_per_group > 0:
                    members_sql += " LIMIT ?"
                    mparams.append(int(max_members_per_group))
                g["members"] = [dict(r) for r in conn.execute(members_sql, mparams).fetchall()]
                g["members_truncated"] = len(g["members"]) < int(g["n"])
                g["group_key"] = f"sha256:{g['digest']}"
                g["count"] = int(g["n"])
                g["wasted_bytes"] = int(g["size_bytes"]) * (int(g["n"]) - 1)
                g["physical_count"] = sum(1 for m in g["members"] if m["document_kind"] == "PHYSICAL_FILE")
                g["member_count_archive"] = sum(1 for m in g["members"] if m["document_kind"] == "ARCHIVE_MEMBER")
        return groups

    def duplicate_totals(self, *, min_size: int = 1, scope_prefix: Optional[str] = None,
                         include_members: bool = True, include_missing: bool = False) -> dict[str, Any]:
        """True aggregate over *all* duplicate groups (groups list may be capped)."""
        kinds = ["PHYSICAL_FILE", "ARCHIVE_MEMBER"] if include_members else ["PHYSICAL_FILE"]
        placeholders = ",".join("?" * len(kinds))
        inner = (f"SELECT COUNT(*) AS n, MIN(f.size_bytes) AS size FROM content_hashes h "
                 f"JOIN files f ON f.id=h.file_id WHERE h.state='OK' AND h.digest IS NOT NULL "
                 f"AND f.document_kind IN ({placeholders}) AND f.size_bytes >= ?")
        params: list[Any] = [*kinds, int(min_size)]
        if not include_missing:
            inner += " AND COALESCE(f.state,'ACTIVE')='ACTIVE'"
        if scope_prefix:
            inner += " AND f.path LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(scope_prefix))
        inner += " GROUP BY h.digest HAVING COUNT(*) > 1"
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(n-1),0), COALESCE(SUM((n-1)*size),0), COALESCE(MAX(n),0) "
                f"FROM ({inner})", params).fetchone()
        return {"groups": int(row[0]), "duplicate_files": int(row[1]),
                "wasted_bytes": int(row[2]), "largest_group": int(row[3])}

    # -- near-duplicate edges ---------------------------------------------
    def replace_near_duplicates(self, edges: Iterable[dict[str, Any]], *, algorithm: str = "simhash+semantic") -> int:
        rows = []
        for e in edges:
            src, dst = int(e["src_id"]), int(e["dst_id"])
            if src == dst:
                continue
            if src > dst:
                src, dst = dst, src
            rows.append((src, dst, e.get("semantic_score"), e.get("lexical_score"),
                         e.get("reason"), algorithm))
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM near_duplicate_edges")
            conn.executemany(
                """INSERT OR REPLACE INTO near_duplicate_edges
                       (src_id, dst_id, semantic_score, lexical_score, reason, algorithm, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                rows,
            )
            conn.commit()
        return len(rows)

    def near_duplicates_for(self, file_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM near_duplicate_edges
                   WHERE src_id=? OR dst_id=?
                   ORDER BY COALESCE(semantic_score,0) DESC LIMIT ?""",
                (int(file_id), int(file_id), int(limit)),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            other = d["dst_id"] if d["src_id"] == int(file_id) else d["src_id"]
            d["other_id"] = other
            out.append(d)
        return out

    def near_duplicate_stats(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM near_duplicate_edges").fetchone()[0]
        return {"edges": int(n)}

    # -- version families --------------------------------------------------
    def replace_version_families(self, families: Iterable[dict[str, Any]]) -> int:
        families = list(families)
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM version_members")
            conn.execute("DELETE FROM version_families")
            for fam in families:
                cur = conn.execute(
                    """INSERT INTO version_families
                           (family_key, base_name, directory, confidence, evidence,
                            member_count, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (fam["family_key"], fam.get("base_name"), fam.get("directory"),
                     fam.get("confidence", "UNORDERED"),
                     json.dumps(fam.get("evidence", {}), ensure_ascii=False),
                     len(fam.get("members", []))),
                )
                fid = int(cur.lastrowid)
                conn.executemany(
                    """INSERT INTO version_members
                           (family_id, file_id, rank, confidence, evidence, is_primary, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    [(fid, int(m["id"]), m.get("rank"), m.get("confidence"),
                      json.dumps(m.get("evidence", {}), ensure_ascii=False),
                      1 if m.get("is_primary") else 0)
                     for m in fam.get("members", [])],
                )
            conn.commit()
        return len(families)

    def get_version_family_for_file(self, file_id: int) -> Optional[dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT family_id FROM version_members WHERE file_id=?", (int(file_id),)
            ).fetchone()
            if row is None:
                return None
            fid = int(row[0])
            fam = conn.execute("SELECT * FROM version_families WHERE id=?", (fid,)).fetchone()
            if fam is None:
                return None
            members = conn.execute(
                """SELECT vm.file_id AS id, vm.rank, vm.confidence, vm.is_primary, vm.evidence,
                          f.path, f.filename, f.size_bytes, f.modified_at,
                          COALESCE(f.state,'ACTIVE') AS state, f.document_kind
                   FROM version_members vm JOIN files f ON f.id=vm.file_id
                   WHERE vm.family_id=? ORDER BY vm.rank ASC, f.path ASC""", (fid,)
            ).fetchall()
        out = dict(fam)
        out["members"] = [dict(m) for m in members]
        return out

    def version_family_stats(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM version_families").fetchone()[0]
            m = conn.execute("SELECT COUNT(*) FROM version_members").fetchone()[0]
        return {"families": int(n), "members": int(m)}

    def prune_missing_relations(self) -> dict[str, int]:
        """Drop near-dup edges and version members that reference inactive files."""
        active = "SELECT id FROM files WHERE COALESCE(state,'ACTIVE')='ACTIVE'"
        with self.db.get_connection() as conn:
            e = conn.execute(
                f"DELETE FROM near_duplicate_edges WHERE src_id NOT IN ({active}) "
                f"OR dst_id NOT IN ({active})").rowcount
            m = conn.execute(
                f"DELETE FROM version_members WHERE file_id NOT IN ({active})").rowcount
            # Families left with fewer than two active members are no longer families;
            # also cascade members of removed families.
            conn.execute(
                "DELETE FROM version_families WHERE id NOT IN "
                "(SELECT family_id FROM version_members GROUP BY family_id HAVING COUNT(*) >= 2)")
            f = conn.execute(
                "DELETE FROM version_members WHERE family_id NOT IN "
                "(SELECT id FROM version_families)").rowcount
            conn.commit()
        return {"near_edges_removed": int(e or 0), "version_members_removed": int(m or 0),
                "family_members_cascaded": int(f or 0)}

    def version_families(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM version_families ORDER BY member_count DESC, id ASC LIMIT ?",
                (int(limit),)).fetchall()]


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"
