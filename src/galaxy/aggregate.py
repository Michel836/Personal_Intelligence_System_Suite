"""Bounded aggregation helpers for the galaxy service (M020).

Kept separate from :mod:`src.galaxy.service` so the orchestration module stays
readable. Everything here operates on already-bounded inputs (a sample, a
cluster assignment or one chunk of ids) and never allocates an all-pairs
corpus matrix.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import numpy.typing as npt

from .clustering import NOISE, ClusterResult

_CHUNK = 500


def _chunks(items: list[int], size: int = _CHUNK) -> Iterable[list[int]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def cohesion_by_cluster(matrix: npt.NDArray[np.float64],
                        result: ClusterResult) -> dict[int, float]:
    out: dict[int, float] = {}
    for cid in range(len(result.centroids)):
        mask = result.labels == cid
        if not mask.any():
            continue
        cent = result.centroids[cid]
        norm = np.linalg.norm(matrix[mask], axis=1, keepdims=True)
        norm[norm == 0.0] = 1.0
        cnorm = float(np.linalg.norm(cent)) or 1.0
        out[cid] = float(np.mean((matrix[mask] / norm) @ (cent / cnorm)))
    return out


def member_rows(ids: list[int], result: ClusterResult,
                matrix: npt.NDArray[np.float64]) -> list[tuple[int, int, float]]:
    rows: list[tuple[int, int, float]] = []
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    norm[norm == 0.0] = 1.0
    unit = matrix / norm
    for idx, fid in enumerate(ids):
        cid = int(result.labels[idx])
        if cid < 0 or cid >= len(result.centroids):
            rows.append((fid, NOISE, 0.0))
            continue
        cent = result.centroids[cid]
        cnorm = float(np.linalg.norm(cent)) or 1.0
        rows.append((fid, cid, float(unit[idx] @ (cent / cnorm))))
    return rows


def centroids(matrix: npt.NDArray[np.float64], labels: npt.NDArray[np.int64],
              k: int) -> npt.NDArray[np.float64]:
    if k <= 0 or matrix.size == 0:
        return np.zeros((0, matrix.shape[1] if matrix.ndim == 2 else 0))
    out = np.zeros((k, matrix.shape[1]), dtype=np.float64)
    for cid in range(k):
        mask = labels == cid
        if mask.any():
            out[cid] = matrix[mask].mean(axis=0)
    return out


def family_of(db: Any, ids: list[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for chunk in _chunks([int(i) for i in ids]):
        ph = ",".join("?" * len(chunk))
        with db.get_connection() as conn:
            for row in conn.execute(
                    f"SELECT file_id, family_id FROM version_members WHERE file_id IN ({ph})",
                    chunk):
                out[int(row[0])] = int(row[1])
    return out


def exact_duplicates(db: Any, fid: int) -> list[dict[str, Any]]:
    try:
        from ..dedup import DedupStore
        h = DedupStore(db).get_hash(fid)
    except Exception:  # noqa: BLE001
        return []
    if not h or not h.get("digest"):
        return []
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT f.id, f.filename, f.extension, f.size_bytes, "
            "COALESCE(f.state,'ACTIVE') AS state "
            "FROM content_hashes h JOIN files f ON f.id=h.file_id "
            "WHERE h.state='OK' AND h.digest=? AND h.file_id != ? LIMIT 50",
            (h["digest"], int(fid))).fetchall()
    return [dict(r) for r in rows]


def bucket(value: str, group: str) -> str | None:
    if not value:
        return None
    value = str(value)
    if group == "day":
        return value[:10]
    if group == "month":
        return value[:7]
    if group == "year":
        return value[:4]
    if group == "week":
        try:
            from datetime import date
            y, m, d = (int(x) for x in value[:10].split("-"))
            iso = date(y, m, d).isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        except Exception:  # noqa: BLE001
            return value[:10]
    return value[:10]


def shared_category_edges(topics: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    cat_map: dict[str, list[int]] = {}
    for cid, topic in topics.items():
        for cat in topic.get("categories") or []:
            cat_map.setdefault(str(cat.get("category")), []).append(int(cid))
    edges: list[dict[str, Any]] = []
    for category, cids in cat_map.items():
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                edges.append({"source": f"c{cids[i]}", "target": f"c{cids[j]}",
                              "type": "SHARED_CATEGORY", "score": 1.0,
                              "evidence": {"category": category}})
    return edges
