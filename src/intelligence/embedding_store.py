"""Persistent, pre-normalized embedding matrix store (M009I.1 / M010-P).

Layout (under ``data/cache/embeddings/<model_key>/``)::

    matrix.npy   float32, row-major, L2-normalized, shape (capacity, dim)
    meta.json    {version, model_key, model_name, dim, dtype, normalized,
                  count, capacity, ids, content_hashes}

Query = a single matrix-vector product (no per-query normalization, no list ->
matrix rebuild). The store validates shape/dim/count/finiteness on load and
refuses to mix models or dimensions.

M010-P: the matrix is stored with reserved *capacity* and updated in place via a
memory-mapped file, so incremental appends are O(appended rows) instead of the
previous O(total rows) full rewrite. Capacity grows geometrically and the file is
replaced atomically (``os.replace``) so an interrupted grow never corrupts the
store. ``meta.json`` remains the source of truth for ``count``/``ids``, which
keeps the on-disk contract (and its corruption detection) unchanged.

M010 scale trial: ``content_hashes`` is a per-row content fingerprint (parallel
to ``ids``). It lets the semantic layer re-embed *changed* content and prune rows
whose document vanished, so stale vectors can never crowd top-k. Legacy stores
without hashes load with empty hashes and are refreshed on first use.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from loguru import logger

STORE_VERSION = 1
_MIN_CAPACITY = 64


class EmbeddingStoreError(Exception):
    """Raised for corruption or model/dimension mismatches."""


@dataclass
class StoreMeta:
    model_key: str
    model_name: str
    dim: int
    count: int = 0
    dtype: str = "float32"
    normalized: bool = True
    version: int = STORE_VERSION
    ids: list[int] = field(default_factory=list)
    content_hashes: list[str] = field(default_factory=list)
    capacity: int = 0

    def hash_map(self) -> dict[int, str]:
        """Return ``{doc_id: content_hash}`` (omits rows with unknown hashes)."""
        if len(self.content_hashes) != len(self.ids):
            return {}
        return {i: h for i, h in zip(self.ids, self.content_hashes, strict=False) if h}


class EmbeddingMatrixStore:
    """Contiguous, pre-normalized embedding matrix persisted to disk."""

    def __init__(self, model_key: str, model_name: str, dim: int, base_dir: Optional[Path] = None):
        self.model_key = model_key
        self.model_name = model_name
        self.dim = int(dim)
        self.base_dir = Path(base_dir) if base_dir else Path("data/cache/embeddings")
        self.dir = self.base_dir / model_key
        self.matrix: Optional[np.ndarray] = None
        self.meta: Optional[StoreMeta] = None

    # -- persistence -------------------------------------------------------
    @property
    def _matrix_path(self) -> Path:
        return self.dir / "matrix.npy"

    @property
    def _meta_path(self) -> Path:
        return self.dir / "meta.json"

    def exists(self) -> bool:
        return self._matrix_path.exists() and self._meta_path.exists()

    def hash_map(self) -> dict[int, str]:
        """Return ``{doc_id: content_hash}`` for the loaded store."""
        if self.meta is None:
            return {}
        return self.meta.hash_map()

    def _read_matrix(self) -> np.ndarray:
        return np.asarray(np.load(self._matrix_path, mmap_mode="r"))

    def _open_rw(self) -> np.ndarray:
        return np.lib.format.open_memmap(self._matrix_path, mode="r+")

    def _write_meta(self) -> None:
        assert self.meta is not None
        self._meta_path.write_text(json.dumps(asdict(self.meta)), encoding="utf-8")

    def load(self) -> bool:
        """Load and validate the store. Returns False if absent/corrupt."""
        if not self.exists():
            return False
        try:
            meta = StoreMeta(**json.loads(self._meta_path.read_text(encoding="utf-8")))
            matrix = self._read_matrix()
            capacity = int(meta.capacity) if meta.capacity else int(matrix.shape[0])
            self._validate(matrix, meta, capacity)
            meta.capacity = capacity
            if len(meta.content_hashes) != meta.count:
                # Legacy/foreign store without hashes: refresh on first use.
                meta.content_hashes = [""] * meta.count
            self.meta, self.matrix = meta, matrix[: meta.count]
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Embedding store corrupt/unreadable ({self.dir}): {exc}")
            self.matrix, self.meta = None, None
            return False

    def _validate(self, matrix: np.ndarray, meta: StoreMeta, capacity: int) -> None:
        if meta.version != STORE_VERSION:
            raise EmbeddingStoreError(f"unsupported store version {meta.version}")
        if meta.model_key != self.model_key:
            raise EmbeddingStoreError(f"model mismatch: store={meta.model_key} requested={self.model_key}")
        if meta.dim != self.dim or matrix.ndim != 2 or matrix.shape[1] != self.dim:
            raise EmbeddingStoreError(
                f"dimension mismatch: store={meta.dim}/{getattr(matrix, 'shape', None)} requested={self.dim}"
            )
        if capacity < meta.count or matrix.shape[0] < meta.count:
            raise EmbeddingStoreError("matrix capacity smaller than declared count")
        if matrix.shape[0] != capacity:
            raise EmbeddingStoreError("matrix shape does not match declared capacity")
        if len(meta.ids) != meta.count:
            raise EmbeddingStoreError("matrix/meta count mismatch")
        if not np.isfinite(matrix[: meta.count]).all():
            raise EmbeddingStoreError("matrix contains non-finite values")

    @staticmethod
    def normalize(matrix: np.ndarray) -> np.ndarray:
        matrix = np.asarray(matrix, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return (matrix / norms).astype(np.float32)

    def _allocate(self, capacity: int) -> np.ndarray:
        self.dir.mkdir(parents=True, exist_ok=True)
        return np.lib.format.open_memmap(
            self._matrix_path, mode="w+", dtype=np.float32, shape=(capacity, self.dim)
        )

    def save(self, ids: Iterable[int], matrix: np.ndarray, hashes: Iterable[str] | None = None) -> None:
        ids = [int(i) for i in ids]
        matrix = self.normalize(matrix)
        if matrix.shape[0] != len(ids):
            raise EmbeddingStoreError("ids/matrix length mismatch")
        if matrix.shape[1] != self.dim:
            raise EmbeddingStoreError("dimension mismatch on save")
        content_hashes = [str(h) for h in hashes] if hashes is not None else [""] * len(ids)
        if len(content_hashes) != len(ids):
            raise EmbeddingStoreError("ids/hash length mismatch")
        capacity = max(len(ids) + max(1024, len(ids) // 10), 1)
        buf = self._allocate(capacity)
        if len(ids):
            buf[: len(ids)] = matrix
        buf.flush()
        self.meta = StoreMeta(
            model_key=self.model_key,
            model_name=self.model_name,
            dim=self.dim,
            count=len(ids),
            ids=ids,
            content_hashes=content_hashes,
            capacity=capacity,
        )
        self._write_meta()
        self.matrix = matrix

    def _ensure_capacity(self, target: int) -> None:
        assert self.meta is not None
        capacity = self.meta.capacity or self.meta.count
        if target <= capacity:
            self.meta.capacity = capacity
            return
        new_capacity = max(target, capacity * 2, _MIN_CAPACITY)
        old = self._read_matrix()
        tmp = self._matrix_path.with_suffix(".npy.tmp")
        new = np.lib.format.open_memmap(
            tmp, mode="w+", dtype=np.float32, shape=(new_capacity, self.dim)
        )
        if self.meta.count:
            new[: self.meta.count] = old[: self.meta.count]
        new.flush()
        del new
        os.replace(tmp, self._matrix_path)
        self.meta.capacity = new_capacity

    # -- incremental -------------------------------------------------------
    def append(self, ids: Iterable[int], matrix: np.ndarray, hashes: Iterable[str] | None = None) -> None:
        """Incrementally upsert rows (replacing existing ids) in place.

        Uses the reserved capacity so repeated small appends are O(rows added)
        rather than O(total rows). Row order is an internal detail (search uses
        the id array for deterministic tie-breaking), but the id/count contract
        is preserved. ``hashes`` stores a per-row content fingerprint so the
        semantic layer can detect changed content and refresh it.
        """
        ids = [int(i) for i in ids]
        matrix = self.normalize(matrix)
        if matrix.shape[0] != len(ids):
            raise EmbeddingStoreError("ids/matrix length mismatch")
        if matrix.shape[1] != self.dim:
            raise EmbeddingStoreError("dimension mismatch on append")
        content_hashes = [str(h) for h in hashes] if hashes is not None else [""] * len(ids)
        if len(content_hashes) != len(ids):
            raise EmbeddingStoreError("ids/hash length mismatch")
        if self.matrix is None or self.meta is None:
            if not self.load():
                self.save(ids, matrix, content_hashes)
                return
        if len(self.meta.content_hashes) != self.meta.count:
            self.meta.content_hashes = [""] * self.meta.count

        id_to_row = {doc_id: row for row, doc_id in enumerate(self.meta.ids)}
        additions = sum(1 for doc_id in ids if doc_id not in id_to_row)
        self._ensure_capacity(self.meta.count + additions)

        buf = self._open_rw()
        for doc_id, vec, chash in zip(ids, matrix, content_hashes, strict=False):
            row = id_to_row.get(doc_id)
            if row is None:
                row = self.meta.count
                self.meta.ids.append(doc_id)
                self.meta.content_hashes.append(chash)
                self.meta.count += 1
                id_to_row[doc_id] = row
            else:
                self.meta.content_hashes[row] = chash
            buf[row] = vec
        buf.flush()
        del buf
        self._write_meta()
        self.matrix = self._read_matrix()[: self.meta.count]

    def prune(self, keep_ids: Iterable[int]) -> int:
        """Drop rows whose ids are not in ``keep_ids``; returns removed count.

        Rows are compacted in place so a deleted/changed document can never
        occupy a top-k slot with a stale vector. The reserved capacity is kept.
        """
        keep = {int(i) for i in keep_ids}
        if (self.matrix is None or self.meta is None) and not self.load():
            return 0
        if len(self.meta.content_hashes) != self.meta.count:
            self.meta.content_hashes = [""] * self.meta.count
        rows = [r for r, doc_id in enumerate(self.meta.ids) if doc_id in keep]
        removed = self.meta.count - len(rows)
        if removed <= 0:
            return 0
        buf = self._open_rw()
        for dst, src in enumerate(rows):
            if dst != src:
                buf[dst] = buf[src]
        buf.flush()
        del buf
        self.meta.ids = [self.meta.ids[r] for r in rows]
        self.meta.content_hashes = [self.meta.content_hashes[r] for r in rows]
        self.meta.count = len(self.meta.ids)
        self._write_meta()
        self.matrix = self._read_matrix()[: self.meta.count]
        return removed

    # -- query -------------------------------------------------------------
    def search(self, query: np.ndarray, top_k: int = 10) -> list[tuple[int, float]]:
        """Cosine top-k against the pre-normalized matrix (single matvec)."""
        if self.matrix is None or self.meta is None or not self.meta.ids or top_k <= 0:
            return []
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        if q.shape[0] != self.dim:
            raise EmbeddingStoreError(f"query dim {q.shape[0]} != store dim {self.dim}")
        norm = float(np.linalg.norm(q))
        if norm == 0.0:
            return []
        scores = (self.matrix @ (q / norm)).astype(np.float32)
        ids = np.asarray(self.meta.ids)
        k = min(int(top_k), len(scores))
        order = np.lexsort((ids, -scores))[:k]
        return [(int(ids[j]), float(scores[j])) for j in order]

    def stats(self) -> dict:
        size = self._matrix_path.stat().st_size if self._matrix_path.exists() else 0
        return {
            "model_key": self.model_key,
            "dim": self.dim,
            "count": int(self.meta.count) if self.meta else 0,
            "capacity": int(self.meta.capacity) if self.meta else 0,
            "disk_bytes": size,
            "ram_bytes": int(self.matrix.nbytes) if self.matrix is not None else 0,
        }
