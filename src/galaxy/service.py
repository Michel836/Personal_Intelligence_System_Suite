"""Canonical galaxy / clustering / topic / contextual service (M020).

This is the single orchestration point used by the UI, the API and the CLI. It
never builds a second corpus: every scope, overlay and contextual signal is read
from the canonical SQLite tables and the existing semantic embedding store.
Projections and clusters are derived, bounded and rebuildable.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from loguru import logger

from ..intelligence.embedding_store import EmbeddingMatrixStore
from .aggregate import (
    bucket as _bucket,
)
from .aggregate import (
    centroids as _centroids,
)
from .aggregate import (
    cohesion_by_cluster as _cohesion_by_cluster,
)
from .aggregate import (
    exact_duplicates as _exact_duplicates,
)
from .aggregate import (
    family_of as _family_of,
)
from .aggregate import (
    member_rows as _member_rows,
)
from .aggregate import (
    shared_category_edges as _shared_category_edges,
)
from .clustering import (
    NOISE,
    ClusterResult,
    available_algorithms,
    cluster,
    cluster_stability,
    select_k,
)
from .projection import PROJECTION_VERSION, available_methods, project
from .store import (
    SCHEMA_VERSION,
    GalaxyStore,
    freshness_signature,
    new_run_id,
    vector_namespace,
)
from .topics import Topic, build_topics

SMALL_MAX = 5_000
MEDIUM_MAX = 25_000
POINT_LIMITS = {"SMALL": 6_000, "MEDIUM": 8_000, "LARGE": 10_000}
DEFAULT_K = 16
MAX_K = 64
CHUNK = 500

SCOPE_KINDS = ("all", "search", "dossier", "category", "language", "date",
               "entity", "graph", "cluster", "prefix", "file_ids")


class GalaxyError(ValueError):
    """Raised for unavailable stores or invalid galaxy requests."""


def scale_tier(count: int) -> str:
    if count <= SMALL_MAX:
        return "SMALL"
    if count <= MEDIUM_MAX:
        return "MEDIUM"
    return "LARGE"


def describe_stack() -> dict[str, Any]:
    return {"projection": available_methods(), "clustering": available_algorithms(),
            "scale_tiers": {"SMALL": f"<= {SMALL_MAX}", "MEDIUM": f"<= {MEDIUM_MAX}",
                            "LARGE": f"> {MEDIUM_MAX}"},
            "version": SCHEMA_VERSION}


def _chunks(items: list[int], size: int = CHUNK) -> Iterable[list[int]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _safe_query(conn: Any, sql: str, params: list[Any]) -> list[Any]:
    """Run a read query, tolerating an optional M015 table that is absent."""
    try:
        return list(conn.execute(sql, params).fetchall())
    except Exception:  # noqa: BLE001 - overlays must degrade, never fail the galaxy
        return []


def detect_store(base_dir: Path | None = None, model_key: str | None = None) -> EmbeddingMatrixStore | None:
    """Find the populated embedding matrix store without loading a model."""
    base = base_dir or Path(os.environ.get("PIS_EMBEDDING_STORE_DIR") or "data/cache/embeddings")
    if not base.exists():
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for child in sorted(base.iterdir()):
        meta_path = child / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        key = str(meta.get("model_key") or child.name)
        if model_key and key != model_key:
            continue
        count = int(meta.get("count") or 0)
        if count <= 0:
            continue
        if best is None or count > best[0]:
            best = (count, meta)
    if best is None:
        return None
    meta = best[1]
    return EmbeddingMatrixStore(str(meta.get("model_key") or "unknown"),
                                str(meta.get("model_name") or meta.get("model_key") or "unknown"),
                                int(meta.get("dim") or 0), base_dir=base)


class GalaxyService:
    def __init__(self, db: Any, *, embedding_store: EmbeddingMatrixStore | None = None,
                 model_key: str | None = None, store: GalaxyStore | None = None) -> None:
        self.db = db
        self.store = store or GalaxyStore(db)
        self._embedding_store = embedding_store
        self._model_key = model_key
        self._resolved: EmbeddingMatrixStore | None = embedding_store

    # -- embedding store ---------------------------------------------------
    def embedding_store(self) -> EmbeddingMatrixStore | None:
        if self._resolved is None:
            self._resolved = detect_store(model_key=self._model_key)
        store = self._resolved
        if store is None:
            return None
        if store.matrix is None and not store.load():
            return None
        return store

    def store_stats(self) -> dict[str, Any]:
        store = self.embedding_store()
        if store is None or store.meta is None:
            return {"available": False, "count": 0, "model_key": None, "dim": None}
        return {"available": True, "count": int(store.meta.count),
                "model_key": store.model_key, "model_name": store.model_name,
                "dim": int(store.dim), "namespace": vector_namespace(store.model_key, store.dim)}

    def current_freshness(self) -> str:
        store = self.embedding_store()
        if store is None or store.meta is None:
            return "unavailable"
        return freshness_signature(self.db, model_key=store.model_key, dim=store.dim,
                                   store_count=int(store.meta.count))

    def vectors_for(self, ids: list[int]) -> tuple[list[int], npt.NDArray[np.float64]]:
        store = self.embedding_store()
        if store is None or store.meta is None or store.matrix is None:
            return [], np.zeros((0, 0))
        id_to_row = {int(d): r for r, d in enumerate(store.meta.ids)}
        ordered = [int(i) for i in ids if int(i) in id_to_row]
        if not ordered:
            return [], np.zeros((0, store.dim))
        rows = [id_to_row[i] for i in ordered]
        return ordered, np.asarray(store.matrix[rows], dtype=np.float64)

    # -- scope -------------------------------------------------------------
    def resolve_scope(self, scope: dict[str, Any] | None = None) -> list[int]:
        scope = dict(scope or {})
        kind = str(scope.get("kind") or "all").lower()
        limit = int(scope.get("limit") or 200_000)
        if kind == "all":
            return self._active_content_ids(limit=limit)
        if kind == "file_ids":
            return [int(i) for i in (scope.get("ids") or [])][:limit]
        if kind == "prefix":
            return self._ids_by_prefix(str(scope.get("prefix") or ""), limit=limit)
        if kind == "date":
            return self._ids_by_date(scope, limit=limit)
        if kind == "search":
            rows = self.db.search_files(scope.get("query") or None, limit=limit)
            return [int(r["id"]) for r in rows]
        if kind == "category":
            rows = self.db.search_files(None, limit=limit, category=scope.get("category"))
            return [int(r["id"]) for r in rows]
        if kind == "language":
            rows = self.db.search_files(None, limit=limit, language=scope.get("language"))
            return [int(r["id"]) for r in rows]
        if kind == "entity":
            rows = self.db.search_files(None, limit=limit, entity_type=scope.get("entity_type"),
                                        entity_value=scope.get("entity_value"))
            return [int(r["id"]) for r in rows]
        if kind == "dossier":
            from ..reports.dossiers import DossierService
            resolved = DossierService(self.db).resolve(str(scope.get("dossier_id") or ""))
            return [int(m["file_id"]) for m in resolved.get("members", [])][:limit]
        if kind == "graph":
            from ..graph import RelationService
            result = RelationService(self.db).neighborhood(int(scope.get("file_id") or 0),
                                                           depth=int(scope.get("depth") or 1),
                                                           max_nodes=min(limit, 200))
            return [int(n["id"]) for n in result.get("nodes", [])]
        if kind == "cluster":
            run_id = str(scope.get("run_id") or "")
            rows = self.store.cluster_members(run_id, cluster_id=scope.get("cluster_id"),
                                              limit=limit)
            return [int(r["file_id"]) for r in rows]
        raise GalaxyError(f"unknown scope kind: {kind}")

    def _active_content_ids(self, *, limit: int) -> list[int]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM files WHERE content_extracted=1 AND content_text IS NOT NULL "
                "AND length(content_text) > 50 AND COALESCE(state,'ACTIVE')='ACTIVE' "
                "ORDER BY id ASC LIMIT ?", (int(limit),)).fetchall()
        return [int(r[0]) for r in rows]

    def _ids_by_prefix(self, prefix: str, *, limit: int) -> list[int]:
        if not prefix:
            return []
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM files WHERE path LIKE ? ESCAPE '\\' "
                "AND COALESCE(state,'ACTIVE')='ACTIVE' ORDER BY id ASC LIMIT ?",
                (f"{escaped}%", int(limit))).fetchall()
        return [int(r[0]) for r in rows]

    def _ids_by_date(self, scope: dict[str, Any], *, limit: int) -> list[int]:
        source = str(scope.get("source") or "modified_at")
        if source not in {"modified_at", "created_at", "indexed_at"}:
            source = "modified_at"
        conditions = [f"{source} IS NOT NULL", "COALESCE(state,'ACTIVE')='ACTIVE'",
                      "content_extracted=1"]
        params: list[Any] = []
        if scope.get("start"):
            conditions.append(f"{source} >= ?")
            params.append(str(scope["start"]))
        if scope.get("end"):
            conditions.append(f"{source} <= ?")
            params.append(str(scope["end"]))
        params.append(int(limit))
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM files WHERE {' AND '.join(conditions)} ORDER BY id ASC LIMIT ?",
                params).fetchall()
        return [int(r[0]) for r in rows]

    @staticmethod
    def describe_scope(scope: dict[str, Any] | None = None) -> dict[str, Any]:
        scope = dict(scope or {})
        kind = str(scope.get("kind") or "all").lower()
        safe = {"kind": kind}
        for key in ("query", "category", "language", "entity_type", "entity_value",
                    "start", "end", "source", "dossier_id", "file_id", "run_id", "cluster_id"):
            if scope.get(key) not in (None, ""):
                safe[key] = scope[key]
        if scope.get("prefix"):
            safe["prefix"] = "<redacted-prefix>"
        return safe

    # -- duplicate / version collapse -------------------------------------
    def collapse_ids(self, ids: list[int], *, exact: bool = True,
                     versions: bool = True) -> tuple[list[int], dict[str, Any]]:
        """Return ``(kept_ids, detail)`` collapsing exact duplicates / versions."""
        keep = [int(i) for i in ids]
        detail: dict[str, Any] = {"exact_removed": 0, "version_removed": 0,
                                  "collapse_enabled": {"exact": exact, "versions": versions}}
        if exact:
            digest_by_id: dict[int, str] = {}
            for chunk in _chunks(keep):
                ph = ",".join("?" * len(chunk))
                with self.db.get_connection() as conn:
                    rows = conn.execute(
                        f"SELECT file_id, digest FROM content_hashes WHERE state='OK' "
                        f"AND digest IS NOT NULL AND file_id IN ({ph})", chunk).fetchall()
                for row in rows:
                    digest_by_id[int(row[0])] = str(row[1])
            rep_by_digest: dict[str, int] = {}
            for fid, digest in digest_by_id.items():
                if digest not in rep_by_digest or fid < rep_by_digest[digest]:
                    rep_by_digest[digest] = fid
            before = len(keep)
            keep = [i for i in keep
                    if digest_by_id.get(i) is None
                    or rep_by_digest.get(digest_by_id[i], i) == i]
            detail["exact_removed"] = before - len(keep)
        if versions:
            primary_by_family: dict[int, int] = {}
            for chunk in _chunks(keep):
                ph = ",".join("?" * len(chunk))
                with self.db.get_connection() as conn:
                    rows = conn.execute(
                        f"SELECT family_id, file_id, is_primary, rank FROM version_members "
                        f"WHERE file_id IN ({ph})", chunk).fetchall()
                for row in rows:
                    fam, fid = int(row[0]), int(row[1])
                    best = primary_by_family.get(fam)
                    if best is None or (int(row[2] or 0) == 1 and best != fid):
                        primary_by_family[fam] = fid
            fam_of = _family_of(self.db, keep)
            before = len(keep)
            keep = [i for i in keep if i == primary_by_family.get(fam_of.get(i, -1), i)]
            detail["version_removed"] = before - len(keep)
        detail["collapsed_count"] = len(ids) - len(keep)
        return keep, detail

    # -- clustering --------------------------------------------------------
    def build_clusters(self, *, scope: dict[str, Any] | None = None,
                       algorithm: str = "minibatch-kmeans", k: int | None = None,
                       seed: int = 0, collapse_duplicates: bool = False,
                       collapse_versions: bool = False, persist: bool = True,
                       auto_k: bool = True) -> dict[str, Any]:
        ids = self.resolve_scope(scope)
        collapsed = 0
        if collapse_duplicates or collapse_versions:
            ids, detail = self.collapse_ids(ids, exact=collapse_duplicates,
                                            versions=collapse_versions)
            collapsed = int(detail["collapsed_count"])
        present, matrix = self.vectors_for(ids)
        if not present:
            raise GalaxyError("no vectors available for the requested scope")
        store = self.embedding_store()
        assert store is not None and store.meta is not None
        selection: dict[str, Any] | None = None
        if k is None and auto_k:
            selection = select_k(matrix, seed=seed)
            k = int(selection["selected_k"])
        if k is None:
            k = DEFAULT_K
        k = max(2, min(int(k), MAX_K, max(2, len(matrix) - 1)))
        result = cluster(matrix, algorithm=algorithm, k=k, seed=seed)
        run_id = new_run_id("clu")
        freshness = freshness_signature(self.db, model_key=store.model_key, dim=store.dim,
                                        store_count=int(store.meta.count))
        if persist:
            self.store.save_cluster_run(
                run_id=run_id, algorithm=result.algorithm, params=result.params,
                model_key=store.model_key, dim=store.dim, freshness=freshness,
                source_scope=self.describe_scope(scope), input_count=len(present),
                collapsed_count=collapsed, k=result.k, noise_count=result.noise_count,
                quality={**result.quality, "selection": selection}, software_version=SCHEMA_VERSION)
            self.store.save_members(run_id, _member_rows(present, result, matrix))
        return {"run_id": run_id, "result": result, "ids": present, "matrix": matrix,
                "selection": selection, "collapsed": collapsed,
                "freshness": freshness, "vector_namespace": vector_namespace(store.model_key, store.dim)}

    def build_topics(self, run_id: str, *, max_docs_per_cluster: int = 120,
                     max_representatives: int = 5, persist: bool = True) -> list[Topic]:
        run = self.store.cluster_run(run_id)
        if run is None:
            raise GalaxyError(f"unknown cluster run: {run_id}")
        members = self.store.cluster_members(run_id, limit=200_000)
        if not members:
            return []
        ids = [int(m["file_id"]) for m in members]
        label_by_id = {int(m["file_id"]): int(m["cluster_id"]) for m in members}
        sim_by_id = {int(m["file_id"]): float(m.get("similarity") or 0.0) for m in members}
        present, matrix = self.vectors_for(ids)
        if not present:
            return []
        labels = np.asarray([label_by_id[i] for i in present], dtype=np.int64)
        k = max(labels.max() + 1 if len(labels) else 0, 0)
        centroids = _centroids(matrix, labels, k)
        cohesion = {}
        for cid in range(k):
            mask = labels == cid
            if mask.any():
                cent = centroids[cid]
                norm = np.linalg.norm(matrix[mask], axis=1, keepdims=True)
                norm[norm == 0.0] = 1.0
                cnorm = float(np.linalg.norm(cent)) or 1.0
                cohesion[cid] = float(np.mean((matrix[mask] / norm) @ (cent / cnorm)))
        topics = build_topics(
            self.db, run_id=run_id, ids=present, labels=labels, centroids=centroids,
            vectors=matrix, cohesion_by_cluster=cohesion,
            max_docs_per_cluster=max_docs_per_cluster,
            max_representatives=max_representatives)
        for topic in topics:
            for rep in topic.representatives:
                rep["similarity"] = sim_by_id.get(int(rep["id"]), rep.get("similarity"))
        if persist:
            self.store.save_topics(list(topics))
        return topics

    def cluster_detail(self, run_id: str, cluster_id: int, *, limit: int = 50) -> dict[str, Any]:
        run = self.store.cluster_run(run_id)
        if run is None:
            raise GalaxyError(f"unknown cluster run: {run_id}")
        members = self.store.cluster_members(run_id, cluster_id=cluster_id, limit=limit)
        topics = self.store.topics(run_id, cluster_id=cluster_id)
        topic = topics[0] if topics else None
        overlay = self.overlays([int(m["file_id"]) for m in members])
        member_rows = []
        for m in members:
            meta = overlay.get(int(m["file_id"]), {})
            member_rows.append({**m, "overlay": meta,
                                "missing": meta.get("state", "MISSING") != "ACTIVE"})
        return {
            "run_id": run_id, "cluster_id": int(cluster_id),
            "size": next((t["size"] for t in topics), len(members)),
            "cohesion": (topic or {}).get("cohesion"),
            "topic": topic,
            "members": member_rows,
            "status": self.store.run_status(run, current_freshness=self.current_freshness()),
            "run": {k: run.get(k) for k in ("algorithm", "params", "k", "quality",
                                            "model_key", "dim", "created_at", "input_count")},
        }

    # -- projection / galaxy ----------------------------------------------
    def galaxy(self, *, scope: dict[str, Any] | None = None, method: str = "pca",
               limit: int | None = None, seed: int = 0, color_by: str = "cluster",
               collapse_duplicates: bool = False, collapse_versions: bool = False,
               aggregate: str | None = None, k: int = DEFAULT_K,
               with_topics: bool = True, persist: bool = False) -> dict[str, Any]:
        ids = self.resolve_scope(scope)
        collapsed = 0
        if collapse_duplicates or collapse_versions:
            ids, detail = self.collapse_ids(ids, exact=collapse_duplicates,
                                            versions=collapse_versions)
            collapsed = int(detail["collapsed_count"])
        present, matrix = self.vectors_for(ids)
        if not present:
            return {"available": False, "reason": "no embedded vectors for scope",
                    "points": [], "clusters": [], "meta": {}}
        tier = scale_tier(len(present))
        effective_limit = int(limit or POINT_LIMITS[tier])
        if aggregate is None:
            aggregate = "clusters" if tier == "LARGE" else "points"
        store = self.embedding_store()
        assert store is not None and store.meta is not None
        freshness = freshness_signature(self.db, model_key=store.model_key, dim=store.dim,
                                        store_count=int(store.meta.count))
        selection = None
        result: ClusterResult | None = None
        if color_by == "cluster" or aggregate == "clusters":
            k = max(2, min(int(k), MAX_K, max(2, len(matrix) - 1)))
            result = cluster(matrix, algorithm="minibatch-kmeans", k=k, seed=seed)
        clusters: list[dict[str, Any]] = []
        points: list[dict[str, Any]] = []
        projection_meta: dict[str, Any] = {}
        cluster_run_id: str | None = None
        if result is not None and persist:
            cluster_run_id = new_run_id("clu")
            self.store.save_cluster_run(
                run_id=cluster_run_id, algorithm=result.algorithm, params=result.params,
                model_key=store.model_key, dim=store.dim, freshness=freshness,
                source_scope=self.describe_scope(scope), input_count=len(present),
                collapsed_count=collapsed, k=result.k, noise_count=result.noise_count,
                quality=result.quality, software_version=SCHEMA_VERSION)
            self.store.save_members(cluster_run_id, _member_rows(present, result, matrix))
        if aggregate == "clusters" and result is not None:
            centroids = result.centroids
            projection = project(list(range(len(centroids))), centroids, method=method, seed=seed) \
                if len(centroids) else None
            cluster_points = []
            labels_list = result.labels
            for cid in range(len(centroids)):
                mask = labels_list == cid
                size = int(mask.sum())
                if not size:
                    continue
                x = float(projection.coords[cid][0]) if projection is not None else 0.0
                y = float(projection.coords[cid][1]) if projection is not None else 0.0
                cluster_points.append({"id": f"c{cid}", "cluster_id": cid, "x": round(x, 6),
                                       "y": round(y, 6), "size": size,
                                       "label": f"cluster {cid} · {size} docs"})
            points = cluster_points
            clusters = self._cluster_summaries(cluster_run_id, result, matrix, present,
                                               with_topics=with_topics, persist=persist)
            projection_meta = projection.as_dict() if projection is not None else {}
            projection_meta["aggregated"] = True
        else:
            sampled_ids, sampled_matrix, sampled = self._sample(present, matrix,
                                                                effective_limit, seed)
            projection = project(sampled_ids, sampled_matrix, method=method, seed=seed)
            labels = None
            if result is not None:
                pos = {int(f): i for i, f in enumerate(present)}
                labels = [int(result.labels[pos[int(i)]]) for i in sampled_ids]
            overlay = self.overlays(sampled_ids)
            for idx, fid in enumerate(sampled_ids):
                meta = overlay.get(int(fid), {})
                entry = {"id": int(fid), "x": round(float(projection.coords[idx][0]), 6),
                         "y": round(float(projection.coords[idx][1]), 6),
                         "cluster_id": (labels[idx] if labels is not None else None),
                         "overlay": meta, "color": self._color_value(color_by, labels, meta, idx)}
                points.append(entry)
            clusters = self._cluster_summaries(cluster_run_id, result, matrix, present,
                                               with_topics=with_topics,
                                               persist=persist) if result is not None else []
            projection_meta = projection.as_dict()
            projection_meta["aggregated"] = False
            projection_meta["sampled"] = sampled

        projection_run_id: str | None = None
        if persist:
            projection_run_id = new_run_id("prj")
            self.store.save_projection_run(
                run_id=projection_run_id, method=method,
                params={"seed": seed, "limit": effective_limit, "aggregate": aggregate},
                model_key=store.model_key, dim=store.dim, freshness=freshness,
                source_scope=self.describe_scope(scope), input_count=len(present),
                sampled=bool(projection_meta.get("sampled")), software_version=SCHEMA_VERSION)
            if result is not None and projection_run_id:
                self.store.save_projection_points(
                    projection_run_id, [(p["id"], p["x"], p["y"], p.get("cluster_id"))
                                        for p in points if isinstance(p["id"], int)])
        return {
            "available": True,
            "tier": tier,
            "method": method,
            "projection": projection_meta,
            "points": points,
            "clusters": clusters,
            "cluster_run_id": cluster_run_id,
            "projection_run_id": projection_run_id,
            "meta": {
                "input_count": len(present),
                "returned_points": len(points),
                "collapsed": collapsed,
                "color_by": color_by,
                "aggregate": aggregate,
                "vector_namespace": vector_namespace(store.model_key, store.dim),
                "freshness": freshness,
                "seed": seed,
                "limits": {"tier": tier, "point_limit": effective_limit},
                "warnings": ["coordinates are an exploratory projection, not literal "
                             "semantic distance"],
                "selection": selection,
                "version": PROJECTION_VERSION,
            },
        }

    def _cluster_summaries(self, run_id: str | None, result: ClusterResult,
                           matrix: npt.NDArray[np.float64], ids: list[int], *,
                           with_topics: bool, persist: bool = False) -> list[dict[str, Any]]:
        sizes = result.sizes()
        cohesion = _cohesion_by_cluster(matrix, result)
        labels: dict[str, str] = {}
        if with_topics and result.k <= MAX_K:
            topic_run = run_id or new_run_id("clu")
            try:
                topics = build_topics(self.db, run_id=topic_run, ids=ids,
                                      labels=result.labels, centroids=result.centroids,
                                      vectors=matrix, cohesion_by_cluster=cohesion,
                                      max_docs_per_cluster=25, max_representatives=3)
                labels = {str(t.cluster_id): t.label for t in topics}
                if persist and run_id:
                    self.store.save_topics(list(topics))
            except Exception as exc:  # noqa: BLE001 - labels are optional
                logger.debug(f"inline topic labels unavailable: {exc}")
        out = []
        for cid, size in sorted(sizes.items()):
            if cid == NOISE:
                continue
            out.append({"cluster_id": int(cid), "size": int(size),
                        "cohesion": (round(cohesion[cid], 6) if cid in cohesion else None),
                        "label": labels.get(str(cid)) or f"cluster {cid}"})
        return out

    @staticmethod
    def _sample(ids: list[int], matrix: npt.NDArray[np.float64], limit: int,
                seed: int) -> tuple[list[int], npt.NDArray[np.float64], bool]:
        if len(ids) <= limit:
            return list(ids), matrix, False
        rng = np.random.default_rng(int(seed))
        idx = np.sort(rng.choice(len(ids), size=int(limit), replace=False))
        return [ids[int(i)] for i in idx], matrix[idx], True

    @staticmethod
    def _color_value(color_by: str, labels: list[int] | None, meta: dict[str, Any],
                     idx: int) -> Any:
        if color_by == "cluster":
            return labels[idx] if labels is not None else None
        if color_by == "category":
            cats = meta.get("categories") or []
            return cats[0] if cats else "uncategorized"
        return meta.get(color_by)

    # -- overlays / metadata ----------------------------------------------
    def overlays(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        """Bounded, PII-free overlay metadata for the given document ids."""
        out: dict[int, dict[str, Any]] = {}
        if not ids:
            return out
        for chunk in _chunks([int(i) for i in ids]):
            ph = ",".join("?" * len(chunk))
            with self.db.get_connection() as conn:
                for row in conn.execute(
                        f"SELECT id, extension, size_bytes, modified_at, priority, "
                        f"document_kind, COALESCE(state,'ACTIVE') AS state FROM files "
                        f"WHERE id IN ({ph})", chunk):
                    fid = int(row["id"])
                    out[fid] = {"extension": row["extension"],
                                "size_bytes": row["size_bytes"],
                                "year": (str(row["modified_at"])[:4] if row["modified_at"] else None),
                                "priority": row["priority"],
                                "document_kind": row["document_kind"],
                                "state": row["state"],
                                "categories": [], "language": None, "sensitivity": None}
                for row in _safe_query(conn,
                        f"SELECT file_id, lang FROM doc_language WHERE file_id IN ({ph})", chunk):
                    out.setdefault(int(row["file_id"]), {})["language"] = row["lang"]
                for row in _safe_query(conn,
                        f"SELECT file_id, category FROM doc_categories WHERE file_id IN ({ph}) "
                        f"ORDER BY score DESC", chunk):
                    out.setdefault(int(row["file_id"]), {}).setdefault("categories", []).append(
                        row["category"])
                for row in _safe_query(conn,
                        f"SELECT file_id, MAX(CASE severity WHEN 'high' THEN 2 WHEN 'medium' THEN 1 "
                        f"ELSE 0 END) AS sev FROM doc_pii WHERE file_id IN ({ph}) GROUP BY file_id",
                        chunk):
                    sev = int(row["sev"] or 0)
                    out.setdefault(int(row["file_id"]), {})["sensitivity"] = (
                        "high" if sev >= 2 else "medium" if sev == 1 else "low")
        return out

    # -- contextual intelligence ------------------------------------------
    def document_context(self, file_id: int, *, neighbor_limit: int = 10) -> dict[str, Any]:
        fid = int(file_id)
        doc = self._document_row(fid)
        if doc is None:
            raise GalaxyError("document not found")
        from ..graph import DocumentGraph, RelationService
        try:
            relations = RelationService(self.db).neighborhood(fid, semantic=False, depth=1,
                                                              max_nodes=40, max_edges=80)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"relations unavailable: {exc}")
            relations = {"nodes": [], "edges": []}
        semantic: list[dict[str, Any]] = []
        try:
            from ..dedup.related import RelatedDocuments
            estore = self.embedding_store()
            if estore is not None:
                semantic = RelatedDocuments(self.db, embed_store=estore).related(
                    fid, limit=neighbor_limit)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"semantic neighbors unavailable: {exc}")
        try:
            priority: dict[str, Any] | None = DocumentGraph(self.db).priority(fid)
        except Exception:  # noqa: BLE001
            priority = None
        return {
            "document": {k: doc.get(k) for k in (
                "id", "filename", "extension", "size_bytes", "modified_at", "priority",
                "document_kind", "state")},
            "intel": self._intel_for(fid),
            "versions": self._versions_for(fid),
            "duplicates": _exact_duplicates(self.db, fid),
            "semantic_neighbors": semantic,
            "relations": relations,
            "timeline_neighbors": self._timeline_neighbors(fid, limit=neighbor_limit),
            "dossiers": self._dossiers_for(fid),
            "priority": priority,
            "cluster_membership": self._cluster_membership(fid),
            "privacy": {"raw_pii_exposed": False,
                        "note": "only masked PII metadata is returned"},
        }

    def _document_row(self, fid: int) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT id, filename, extension, size_bytes, modified_at, priority, "
                "document_kind, COALESCE(state,'ACTIVE') AS state FROM files WHERE id=?",
                (fid,)).fetchone()
        return dict(row) if row else None

    def _intel_for(self, fid: int) -> dict[str, Any]:
        try:
            from ..intel import IntelStore
            store = IntelStore(self.db)
            lang = store.get_language(fid) or {}
            cats = [{"category": c["category"], "score": c.get("score"), "source": c.get("source")}
                    for c in store.get_categories(fid)]
            ents = [{"type": e["entity_type"], "display": e.get("display_value"),
                     "count": e.get("count")} for e in store.get_entities(fid)][:30]
            pii = [{"type": p["pii_type"], "severity": p.get("severity"), "masked": p.get("masked")}
                   for p in store.get_pii(fid)]
            return {"language": lang.get("lang"), "categories": cats, "entities": ents,
                    "pii": pii, "max_severity": store.max_severity(fid)}
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"intel unavailable: {exc}")
            return {"language": None, "categories": [], "entities": [], "pii": [],
                    "max_severity": None}

    def _versions_for(self, fid: int) -> dict[str, Any] | None:
        try:
            from ..dedup import DedupStore
            fam = DedupStore(self.db).get_version_family_for_file(fid)
        except Exception:  # noqa: BLE001
            return None
        if not fam:
            return None
        return {"family_key": fam.get("family_key"), "confidence": fam.get("confidence"),
                "member_count": len(fam.get("members", [])),
                "members": [{"id": m.get("id"), "is_primary": bool(m.get("is_primary")),
                             "rank": m.get("rank"), "state": m.get("state")}
                            for m in fam.get("members", [])]}

    def _timeline_neighbors(self, fid: int, *, limit: int, window_days: int = 2) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT modified_at FROM files WHERE id=?", (fid,)).fetchone()
            if row is None or not row[0]:
                return []
            rows = conn.execute(
                "SELECT id, modified_at FROM files WHERE id != ? AND modified_at IS NOT NULL "
                "AND ABS(julianday(modified_at) - julianday(?)) <= ? "
                "AND COALESCE(state,'ACTIVE')='ACTIVE' ORDER BY ABS("
                "julianday(modified_at) - julianday(?)) ASC LIMIT ?",
                (fid, row[0], float(window_days), row[0], int(limit))).fetchall()
        return [{"id": int(r["id"]), "date": r["modified_at"], "date_source": "modified_at",
                 "confidence": "HIGH"} for r in rows]

    def _dossiers_for(self, fid: int) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            try:
                rows = conn.execute(
                    "SELECT d.dossier_id, d.name, d.mode FROM dossier_documents dd "
                    "JOIN dossiers d ON d.dossier_id = dd.dossier_id "
                    "WHERE dd.file_id=? AND COALESCE(dd.manual,1) != -1", (fid,)).fetchall()
            except Exception:  # noqa: BLE001
                return []
        return [{"dossier_id": r["dossier_id"], "name": r["name"], "mode": r["mode"]}
                for r in rows]

    def _cluster_membership(self, fid: int) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            try:
                rows = conn.execute(
                    "SELECT m.run_id, m.cluster_id, m.similarity, t.label "
                    "FROM galaxy_cluster_members m LEFT JOIN galaxy_topics t "
                    "ON t.run_id=m.run_id AND t.cluster_id=m.cluster_id "
                    "WHERE m.file_id=? ORDER BY m.run_id DESC LIMIT 5", (fid,)).fetchall()
            except Exception:  # noqa: BLE001
                return []
        return [{"run_id": r["run_id"], "cluster_id": int(r["cluster_id"]),
                 "similarity": r["similarity"], "label": r["label"]} for r in rows]

    # -- cluster relation graph -------------------------------------------
    def cluster_graph(self, run_id: str, *, max_edges: int = 60,
                      neighbor_edges: int = 3) -> dict[str, Any]:
        run = self.store.cluster_run(run_id)
        if run is None:
            raise GalaxyError(f"unknown cluster run: {run_id}")
        topics = {t["cluster_id"]: t for t in self.store.topics(run_id)}
        members = self.store.cluster_members(run_id, limit=200_000)
        ids = [int(m["file_id"]) for m in members]
        label_by_id = {int(m["file_id"]): int(m["cluster_id"]) for m in members}
        present, matrix = self.vectors_for(ids)
        labels = np.asarray([label_by_id[i] for i in present], dtype=np.int64)
        k = int(labels.max()) + 1 if len(labels) else 0
        centroids = _centroids(matrix, labels, k)
        nodes = []
        for cid in range(k):
            size = int((labels == cid).sum())
            if not size:
                continue
            topic = topics.get(cid, {})
            nodes.append({"id": f"c{cid}", "cluster_id": cid, "size": size,
                          "label": topic.get("label") or f"cluster {cid}",
                          "top_terms": [t["term"] for t in (topic.get("terms") or [])[:5]]})
        edges: list[dict[str, Any]] = []
        if len(centroids) >= 2:
            norm = np.linalg.norm(centroids, axis=1, keepdims=True)
            norm[norm == 0.0] = 1.0
            unit = centroids / norm
            sim = unit @ unit.T
            np.fill_diagonal(sim, -1.0)
            seen: set[tuple[int, int]] = set()
            for cid in range(len(centroids)):
                order = np.argsort(-sim[cid])[:max(1, int(neighbor_edges))]
                for other in order:
                    other = int(other)
                    key = (min(cid, other), max(cid, other))
                    if key in seen or other == cid:
                        continue
                    seen.add(key)
                    edges.append({"source": f"c{cid}", "target": f"c{other}",
                                  "type": "CENTROID_SIMILARITY",
                                  "score": round(float(sim[cid][other]), 6),
                                  "evidence": {"method": "cosine of cluster centroids"}})
                    if len(edges) >= max_edges:
                        break
                if len(edges) >= max_edges:
                    break
            shared = _shared_category_edges(topics)
            for edge in shared:
                if len(edges) >= max_edges:
                    break
                edges.append(edge)
        return {"run_id": run_id, "nodes": nodes, "edges": edges[:max_edges],
                "bounds": {"max_edges": max_edges, "neighbor_edges": neighbor_edges},
                "note": "aggregate evidence only (centroid similarity / shared categories)"}

    # -- topic over time ---------------------------------------------------
    def topic_over_time(self, run_id: str, *, group: str = "month",
                        source: str = "modified_at") -> dict[str, Any]:
        allowed = {"modified_at", "created_at", "indexed_at"}
        source = source if source in allowed else "modified_at"
        members = self.store.cluster_members(run_id, limit=200_000)
        if not members:
            return {"run_id": run_id, "group": group, "date_source": source, "series": []}
        labels = {int(m["file_id"]): int(m["cluster_id"]) for m in members}
        topics = {t["cluster_id"]: t.get("label") or f"cluster {t['cluster_id']}"
                  for t in self.store.topics(run_id)}
        counters: dict[tuple[str, int], int] = {}
        for chunk in _chunks(list(labels)):
            ph = ",".join("?" * len(chunk))
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    f"SELECT id, {source} AS dt FROM files WHERE id IN ({ph}) AND {source} IS NOT NULL",
                    chunk).fetchall()
            for row in rows:
                bucket = _bucket(str(row["dt"]), group)
                if not bucket:
                    continue
                key = (bucket, labels[int(row["id"])])
                counters[key] = counters.get(key, 0) + 1
        series = [{"bucket": bucket, "cluster_id": cid,
                   "label": topics.get(cid, f"cluster {cid}"), "count": count}
                  for (bucket, cid), count in sorted(counters.items())]
        return {"run_id": run_id, "group": group, "date_source": source,
                "confidence": "MEDIUM" if source != "modified_at" else "HIGH",
                "series": series,
                "note": "date source is explicit and never silently combined"}

    # -- exports -----------------------------------------------------------
    def create_dossier_from_cluster(self, run_id: str, cluster_id: int, name: str) -> dict[str, Any]:
        members = self.store.cluster_members(run_id, cluster_id=cluster_id, limit=200_000)
        ids = [int(m["file_id"]) for m in members]
        if not ids:
            raise GalaxyError("cluster has no members")
        from ..reports.dossiers import DossierService
        dossier = DossierService(self.db).create(
            name, mode="STATIC", description=f"Cluster {cluster_id} of run {run_id}",
            file_ids=ids)
        return {"dossier": dossier, "member_count": len(ids), "run_id": run_id,
                "cluster_id": int(cluster_id)}

    def report_from_cluster(self, run_id: str, cluster_id: int, title: str,
                            *, privacy_mode: str = "FULL_LOCAL") -> dict[str, Any]:
        members = self.store.cluster_members(run_id, cluster_id=cluster_id, limit=20_000)
        ids = [int(m["file_id"]) for m in members]
        if not ids:
            raise GalaxyError("cluster has no members")
        topics = self.store.topics(run_id, cluster_id=cluster_id)
        label = topics[0]["label"] if topics else f"cluster {cluster_id}"
        from ..reports.export import ExportService
        definition = ExportService(self.db).create_definition(
            "PROJECT", title, description=f"Galaxy cluster {cluster_id}: {label}",
            privacy_mode=privacy_mode, document_ids=ids,
            options={"galaxy_run_id": run_id, "galaxy_cluster_id": cluster_id,
                     "galaxy_label": label})
        return {"report_id": definition.report_id, "cluster_id": int(cluster_id),
                "label": label, "document_count": len(ids), "run_id": run_id}

    # -- freshness ---------------------------------------------------------
    def status(self) -> dict[str, Any]:
        latest = self.store.latest_cluster_run()
        current = self.current_freshness()
        return {
            "vector_store": self.store_stats(),
            "current_freshness": current,
            "latest_cluster_run": (self.store.run_status(latest, current_freshness=current)
                                   if latest else None),
            "derived": self.store.stats(),
            "rebuildable": self.store.rebuildable(),
        }

    def cluster_stability(self, run_id: str, *, seeds: tuple[int, ...] = (0, 1)) -> dict[str, Any]:
        run = self.store.cluster_run(run_id)
        if run is None:
            raise GalaxyError(f"unknown cluster run: {run_id}")
        members = self.store.cluster_members(run_id, limit=200_000)
        ids = [int(m["file_id"]) for m in members]
        present, matrix = self.vectors_for(ids)
        if not present:
            return {"ari": None}
        k = int(run.get("k") or DEFAULT_K)
        return cluster_stability(matrix, algorithm=str(run.get("algorithm")),
                                 k=k, seeds=seeds)

    def incremental_reassign(self, run_id: str, *, new_ids: list[int]) -> dict[str, Any]:
        """Assign new documents to existing cluster centroids (no full rebuild)."""
        run = self.store.cluster_run(run_id)
        if run is None:
            raise GalaxyError(f"unknown cluster run: {run_id}")
        members = self.store.cluster_members(run_id, limit=200_000)
        ids = [int(m["file_id"]) for m in members]
        label_by_id = {int(m["file_id"]): int(m["cluster_id"]) for m in members}
        present, matrix = self.vectors_for(ids)
        if not present:
            raise GalaxyError("run has no resolvable vectors")
        labels = np.asarray([label_by_id[i] for i in present], dtype=np.int64)
        k = int(labels.max()) + 1 if len(labels) else 0
        centroids = _centroids(matrix, labels, k)
        new_present, new_matrix = self.vectors_for([int(i) for i in new_ids])
        if not new_present or len(centroids) == 0:
            return {"assigned": 0}
        norm = np.linalg.norm(new_matrix, axis=1, keepdims=True)
        norm[norm == 0.0] = 1.0
        cnorm = np.linalg.norm(centroids, axis=1, keepdims=True)
        cnorm[cnorm == 0.0] = 1.0
        sims = (new_matrix / norm) @ (centroids / cnorm).T
        assigned = [int(np.argmax(sims[i])) for i in range(len(new_present))]
        rows = [(fid, cid, float(sims[i][cid])) for i, (fid, cid) in enumerate(zip(new_present, assigned, strict=False))]
        self.store.save_members(run_id, rows)
        return {"assigned": len(rows), "run_id": run_id,
                "note": "incremental assignment to existing centroids; no full rebuild"}



