"""Persistent, pre-normalized embedding matrix store (M009I.1).

Layout (under ``data/cache/embeddings/<model_key>/``)::

    matrix.npy   float32, row-major, L2-normalized, shape (count, dim)
    meta.json    {version, model_key, model_name, dim, dtype, normalized, count, ids}

Query = a single matrix-vector product (no per-query normalization, no list ->
matrix rebuild). The store validates shape/dim/count/finiteness on load and
refuses to mix models or dimensions.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from loguru import logger

STORE_VERSION = 1


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

    def load(self) -> bool:
        """Load and validate the store. Returns False if absent/corrupt."""
        if not self.exists():
            return False
        try:
            meta = StoreMeta(**json.loads(self._meta_path.read_text(encoding="utf-8")))
            matrix = np.load(self._matrix_path, allow_pickle=False)
            self._validate(matrix, meta)
            self.meta, self.matrix = meta, matrix
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Embedding store corrupt/unreadable ({self.dir}): {exc}")
            self.matrix, self.meta = None, None
            return False

    def _validate(self, matrix: np.ndarray, meta: StoreMeta) -> None:
        if meta.version != STORE_VERSION:
            raise EmbeddingStoreError(f"unsupported store version {meta.version}")
        if meta.model_key != self.model_key:
            raise EmbeddingStoreError(f"model mismatch: store={meta.model_key} requested={self.model_key}")
        if meta.dim != self.dim or matrix.ndim != 2 or matrix.shape[1] != self.dim:
            raise EmbeddingStoreError(f"dimension mismatch: store={meta.dim}/{getattr(matrix,'shape',None)} requested={self.dim}")
        if matrix.shape[0] != meta.count or len(meta.ids) != meta.count:
            raise EmbeddingStoreError("matrix/meta count mismatch")
        if not np.isfinite(matrix).all():
            raise EmbeddingStoreError("matrix contains non-finite values")

    @staticmethod
    def normalize(matrix: np.ndarray) -> np.ndarray:
        matrix = np.asarray(matrix, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return (matrix / norms).astype(np.float32)

    def save(self, ids: Iterable[int], matrix: np.ndarray) -> None:
        ids = [int(i) for i in ids]
        matrix = self.normalize(matrix)
        if matrix.shape[0] != len(ids):
            raise EmbeddingStoreError("ids/matrix length mismatch")
        if matrix.shape[1] != self.dim:
            raise EmbeddingStoreError("dimension mismatch on save")
        self.dir.mkdir(parents=True, exist_ok=True)
        np.save(self._matrix_path, matrix)
        self.meta = StoreMeta(
            model_key=self.model_key, model_name=self.model_name, dim=self.dim,
            count=len(ids), ids=ids,
        )
        self._meta_path.write_text(json.dumps(asdict(self.meta)), encoding="utf-8")
        self.matrix = matrix

    # -- incremental -------------------------------------------------------
    def append(self, ids: Iterable[int], matrix: np.ndarray) -> None:
        """Incrementally upsert rows (replacing existing ids), keeping normalized."""
        ids = [int(i) for i in ids]
        matrix = self.normalize(matrix)
        if matrix.shape[0] != len(ids):
            raise EmbeddingStoreError("ids/matrix length mismatch")
        if self.matrix is None or self.meta is None:
            if not self.load():
                self.save(ids, matrix)
                return
        incoming = {doc_id: row for doc_id, row in zip(ids, matrix)}
        kept_ids = [i for i in self.meta.ids if i not in incoming]
        keep_mask = np.array([i not in incoming for i in self.meta.ids])
        kept = self.matrix[keep_mask] if self.matrix.size else np.zeros((0, self.dim), dtype=np.float32)
        new_ids = kept_ids + ids
        new_matrix = np.vstack([kept, matrix]) if kept.size else matrix
        self.save(new_ids, new_matrix)

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
            "model_key": self.model_key, "dim": self.dim,
            "count": int(self.meta.count) if self.meta else 0,
            "disk_bytes": size, "ram_bytes": int(self.matrix.nbytes) if self.matrix is not None else 0,
        }
