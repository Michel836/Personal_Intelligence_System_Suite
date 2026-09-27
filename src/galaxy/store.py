"""Additive persistence for clustering/projection runs (M020).

Everything here is **derived and rebuildable**. Tables live beside ``files`` in
the canonical SQLite database (never a second corpus database) and every run
records the algorithm, parameters, vector namespace (model + dimension),
freshness signature, source scope, input count and software version.

The derived tables can be dropped at any time without touching the canonical
corpus; :meth:`GalaxyStore.rebuildable` documents that contract.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "m020.1"


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def vector_namespace(model_key: str, dim: int) -> str:
    return f"{model_key}:{int(dim)}"


def freshness_signature(db: Any, *, model_key: str, dim: int, store_count: int) -> str:
    """Bind a run to the vector namespace and the current semantic generation.

    Any embedding refresh / prune / document change bumps the semantic
    generation, so a mismatch marks the run **stale** instead of silently
    pretending an old clustering is current.
    """
    try:
        generation = int(db.semantic_generation())
    except Exception:  # noqa: BLE001 - older DBs may lack the table
        generation = 0
    blob = f"{model_key}|{int(dim)}|{int(store_count)}|{generation}".encode()
    return hashlib.sha256(blob).hexdigest()[:32]


class GalaxyStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._ensure()

    def _ensure(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS galaxy_cluster_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT,
                    algorithm TEXT NOT NULL,
                    params TEXT,
                    model_key TEXT,
                    dim INTEGER,
                    vector_namespace TEXT,
                    freshness TEXT,
                    source_scope TEXT,
                    input_count INTEGER,
                    collapsed_count INTEGER DEFAULT 0,
                    k INTEGER,
                    noise_count INTEGER DEFAULT 0,
                    quality TEXT,
                    software_version TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS galaxy_cluster_members (
                    run_id TEXT NOT NULL,
                    file_id INTEGER NOT NULL,
                    cluster_id INTEGER NOT NULL,
                    similarity REAL,
                    PRIMARY KEY (run_id, file_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_galaxy_members_cluster "
                         "ON galaxy_cluster_members(run_id, cluster_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS galaxy_topics (
                    run_id TEXT NOT NULL,
                    cluster_id INTEGER NOT NULL,
                    label TEXT,
                    terms TEXT,
                    entities TEXT,
                    categories TEXT,
                    size INTEGER,
                    cohesion REAL,
                    representatives TEXT,
                    evidence TEXT,
                    PRIMARY KEY (run_id, cluster_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS galaxy_projection_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT,
                    method TEXT NOT NULL,
                    params TEXT,
                    model_key TEXT,
                    dim INTEGER,
                    vector_namespace TEXT,
                    freshness TEXT,
                    source_scope TEXT,
                    input_count INTEGER,
                    sampled INTEGER DEFAULT 0,
                    software_version TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS galaxy_projection_points (
                    run_id TEXT NOT NULL,
                    file_id INTEGER NOT NULL,
                    x REAL,
                    y REAL,
                    cluster_id INTEGER,
                    PRIMARY KEY (run_id, file_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_galaxy_points_run "
                         "ON galaxy_projection_points(run_id)")
            conn.commit()

    # -- writes ------------------------------------------------------------
    def save_cluster_run(self, *, run_id: str, algorithm: str, params: dict[str, Any],
                         model_key: str, dim: int, freshness: str, source_scope: dict[str, Any],
                         input_count: int, collapsed_count: int, k: int, noise_count: int,
                         quality: dict[str, Any], software_version: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO galaxy_cluster_runs
                   (run_id, created_at, algorithm, params, model_key, dim, vector_namespace,
                    freshness, source_scope, input_count, collapsed_count, k, noise_count,
                    quality, software_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, _now_iso(), algorithm, json.dumps(params, sort_keys=True),
                 model_key, int(dim), vector_namespace(model_key, dim), freshness,
                 json.dumps(source_scope, sort_keys=True), int(input_count),
                 int(collapsed_count), int(k), int(noise_count),
                 json.dumps(quality, sort_keys=True), software_version),
            )
            conn.commit()

    def save_members(self, run_id: str, rows: list[tuple[int, int, float]]) -> None:
        with self.db.get_connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO galaxy_cluster_members(run_id, file_id, cluster_id, similarity) "
                "VALUES (?, ?, ?, ?)",
                [(run_id, int(fid), int(cid), float(sim)) for fid, cid, sim in rows],
            )
            conn.commit()

    def save_topics(self, topics: list[Any]) -> None:
        with self.db.get_connection() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO galaxy_topics
                   (run_id, cluster_id, label, terms, entities, categories, size, cohesion,
                    representatives, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(t.run_id, int(t.cluster_id), t.label,
                  json.dumps([{"term": term, "weight": round(float(w), 6)}
                              for term, w in t.terms]),
                  json.dumps(t.entities, ensure_ascii=False),
                  json.dumps(t.categories, ensure_ascii=False),
                  int(t.size), (float(t.cohesion) if t.cohesion is not None else None),
                  json.dumps(t.representatives, ensure_ascii=False),
                  json.dumps(t.evidence, ensure_ascii=False)) for t in topics],
            )
            conn.commit()

    def save_projection_run(self, *, run_id: str, method: str, params: dict[str, Any],
                            model_key: str, dim: int, freshness: str,
                            source_scope: dict[str, Any], input_count: int,
                            sampled: bool, software_version: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO galaxy_projection_runs
                   (run_id, created_at, method, params, model_key, dim, vector_namespace,
                    freshness, source_scope, input_count, sampled, software_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, _now_iso(), method, json.dumps(params, sort_keys=True),
                 model_key, int(dim), vector_namespace(model_key, dim), freshness,
                 json.dumps(source_scope, sort_keys=True), int(input_count),
                 1 if sampled else 0, software_version),
            )
            conn.commit()

    def save_projection_points(self, run_id: str, rows: list[tuple[int, float, float, int | None]]) -> None:
        with self.db.get_connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO galaxy_projection_points(run_id, file_id, x, y, cluster_id) "
                "VALUES (?, ?, ?, ?, ?)",
                [(run_id, int(fid), float(x), float(y),
                  (int(cid) if cid is not None else None)) for fid, x, y, cid in rows],
            )
            conn.commit()

    # -- reads -------------------------------------------------------------
    def _row(self, table: str, run_id: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def cluster_run(self, run_id: str) -> dict[str, Any] | None:
        run = self._row("galaxy_cluster_runs", run_id)
        if run:
            run["params"] = _load_json(run.get("params"), {})
            run["source_scope"] = _load_json(run.get("source_scope"), {})
            run["quality"] = _load_json(run.get("quality"), {})
        return run

    def projection_run(self, run_id: str) -> dict[str, Any] | None:
        run = self._row("galaxy_projection_runs", run_id)
        if run:
            run["params"] = _load_json(run.get("params"), {})
            run["source_scope"] = _load_json(run.get("source_scope"), {})
        return run

    def latest_cluster_run(self, *, model_key: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT run_id FROM galaxy_cluster_runs"
        params: list[Any] = []
        if model_key:
            sql += " WHERE model_key=?"
            params.append(model_key)
        sql += " ORDER BY created_at DESC, run_id DESC LIMIT 1"
        with self.db.get_connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return self.cluster_run(str(row[0])) if row else None

    def latest_projection_run(self, *, model_key: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT run_id FROM galaxy_projection_runs"
        params: list[Any] = []
        if model_key:
            sql += " WHERE model_key=?"
            params.append(model_key)
        sql += " ORDER BY created_at DESC, run_id DESC LIMIT 1"
        with self.db.get_connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return self.projection_run(str(row[0])) if row else None

    def cluster_members(self, run_id: str, *, cluster_id: int | None = None,
                        limit: int = 5000) -> list[dict[str, Any]]:
        sql = ("SELECT file_id, cluster_id, similarity FROM galaxy_cluster_members "
               "WHERE run_id=?")
        params: list[Any] = [run_id]
        if cluster_id is not None:
            sql += " AND cluster_id=?"
            params.append(int(cluster_id))
        sql += " ORDER BY similarity DESC, file_id ASC LIMIT ?"
        params.append(int(limit))
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def topics(self, run_id: str, *, cluster_id: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM galaxy_topics WHERE run_id=?"
        params: list[Any] = [run_id]
        if cluster_id is not None:
            sql += " AND cluster_id=?"
            params.append(int(cluster_id))
        sql += " ORDER BY size DESC, cluster_id ASC"
        with self.db.get_connection() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for row in rows:
            for key in ("terms", "entities", "categories", "representatives", "evidence"):
                row[key] = _load_json(row.get(key), [] if key != "evidence" else {})
        return rows

    def projection_points(self, run_id: str, *, limit: int = 20000) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT file_id, x, y, cluster_id FROM galaxy_projection_points "
                "WHERE run_id=? ORDER BY file_id ASC LIMIT ?", (run_id, int(limit))).fetchall()]

    def run_status(self, run: dict[str, Any], *, current_freshness: str) -> dict[str, Any]:
        """Fresh/stale status for a run against the current vector provenance."""
        fresh = str(run.get("freshness") or "") == str(current_freshness)
        return {
            "run_id": run.get("run_id"),
            "fresh": fresh,
            "status": "FRESH" if fresh else "STALE",
            "recorded_freshness": run.get("freshness"),
            "current_freshness": current_freshness,
            "vector_namespace": run.get("vector_namespace"),
            "note": ("derived data is rebuildable; a stale run must be rebuilt or "
                     "incrementally reassigned"),
        }

    def stats(self) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            def count(table: str) -> int:
                try:
                    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                except Exception:  # noqa: BLE001
                    return 0
            return {"cluster_runs": count("galaxy_cluster_runs"),
                    "cluster_members": count("galaxy_cluster_members"),
                    "topics": count("galaxy_topics"),
                    "projection_runs": count("galaxy_projection_runs"),
                    "projection_points": count("galaxy_projection_points")}

    def rebuildable(self) -> dict[str, Any]:
        return {
            "canonical": "sqlite (files + semantic store)",
            "derived_tables": ["galaxy_cluster_runs", "galaxy_cluster_members", "galaxy_topics",
                               "galaxy_projection_runs", "galaxy_projection_points"],
            "drop_safe": True,
            "note": "dropping these tables never touches the corpus; runs are rebuilt from vectors",
            "schema_version": SCHEMA_VERSION,
        }


def _load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, dict | list):
        return value
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return default
