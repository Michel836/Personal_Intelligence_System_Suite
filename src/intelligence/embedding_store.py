"""Persistent, pre-normalized embedding matrix store (M009I.1 / M010-P / M011).

Layout (under ``data/cache/embeddings/<model_key>/``)::

    matrix.npy   float32, row-major, L2-normalized, shape (capacity, dim)
    ids.npy      int64, shape (capacity,)          -- row -> document id
    hashes.npy   bytes S32, shape (capacity,)      -- row -> content version
    meta.json    {version, model_key, model_name, dim, dtype, normalized,
                  count, capacity}                 -- small scalar metadata

Query = a single matrix-vector product (no per-query normalization, no list ->
matrix rebuild). The store validates shape/dim/count/finiteness on load and
refuses to mix models or dimensions.

Capacity is reserved and updated in place via memory-mapped files, so incremental
appends are O(appended rows). Capacity grows geometrically; each file is replaced
atomically (``os.replace``) so an interrupted grow never corrupts the store.

M011: ``ids`` and ``content_hashes`` moved out of ``meta.json`` into fixed-width
binary sidecars. A refresh that touches K rows now rewrites O(K) bytes of
metadata instead of the whole id/hash list, so refresh cost scales with the
change set rather than the corpus. Legacy v1 stores (ids/hashes inside
``meta.json``) are migrated once on first load; a failed migration is treated as
a corrupt store and safely rebuilt.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from loguru import logger

STORE_VERSION = 2
_MIN_CAPACITY = 64
_HASH_BYTES = 32


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
        # Row -> id numpy view for O(1) query-time use (avoids list->array).
        self._ids_arr: Optional[np.ndarray] = None

    # -- paths -------------------------------------------------------------
    @property
    def _matrix_path(self) -> Path:
        return self.dir / "matrix.npy"

    @property
    def _ids_path(self) -> Path:
        return self.dir / "ids.npy"

    @property
    def _hashes_path(self) -> Path:
        return self.dir / "hashes.npy"

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

    # -- hash codec --------------------------------------------------------
    @staticmethod
    def _enc_hash(h: str) -> bytes:
        raw = (h or "").encode("utf-8")[:_HASH_BYTES]
        return raw.ljust(_HASH_BYTES, b"\x00")

    @staticmethod
    def _dec_hash(b) -> str:
        return bytes(b).rstrip(b"\x00").decode("utf-8", "ignore")

    # -- io helpers --------------------------------------------------------
    def _read_matrix(self) -> np.ndarray:
        return np.asarray(np.load(self._matrix_path, mmap_mode="r"))

    def _read_ids(self) -> np.ndarray:
        return np.asarray(np.load(self._ids_path, mmap_mode="r"))

    def _read_hashes(self) -> np.ndarray:
        return np.asarray(np.load(self._hashes_path, mmap_mode="r"))

    def _open_matrix_rw(self) -> np.ndarray:
        return np.lib.format.open_memmap(self._matrix_path, mode="r+")

    def _open_ids_rw(self) -> np.ndarray:
        return np.lib.format.open_memmap(self._ids_path, mode="r+")

    def _open_hashes_rw(self) -> np.ndarray:
        return np.lib.format.open_memmap(self._hashes_path, mode="r+")

    def _write_meta(self) -> None:
        assert self.meta is not None
        self._meta_path.write_text(
            json.dumps({
                "version": STORE_VERSION,
                "model_key": self.meta.model_key,
                "model_name": self.meta.model_name,
                "dim": self.meta.dim,
                "dtype": self.meta.dtype,
                "normalized": self.meta.normalized,
                "count": self.meta.count,
                "capacity": self.meta.capacity,
            }),
            encoding="utf-8",
        )

    def _write_sidecars(self, ids, hashes, capacity: int) -> int:
        """(Re)write ids.npy/hashes.npy for ``capacity`` rows. Returns capacity."""
        self.dir.mkdir(parents=True, exist_ok=True)
        cap = max(int(capacity), len(ids), _MIN_CAPACITY)
        idbuf = np.lib.format.open_memmap(self._ids_path, mode="w+", dtype=np.int64, shape=(cap,))
        hbuf = np.lib.format.open_memmap(self._hashes_path, mode="w+", dtype=f"S{_HASH_BYTES}", shape=(cap,))
        for r, doc_id in enumerate(ids):
            idbuf[r] = int(doc_id)
            hbuf[r] = self._enc_hash(hashes[r] if r < len(hashes) else "")
        idbuf.flush()
        hbuf.flush()
        del idbuf, hbuf
        return cap

    def _load_sidecars_into_meta(self, meta: StoreMeta) -> None:
        ids_arr = self._read_ids()
        hashes_arr = self._read_hashes()
        if ids_arr.shape[0] != meta.capacity or hashes_arr.shape[0] != meta.capacity:
            raise EmbeddingStoreError("sidecar capacity mismatch")
        meta.ids = [int(x) for x in ids_arr[: meta.count]]
        meta.content_hashes = [self._dec_hash(x) for x in hashes_arr[: meta.count]]
        self._ids_arr = ids_arr

    # -- load --------------------------------------------------------------
    def load(self) -> bool:
        """Load and validate the store. Returns False if absent/corrupt."""
        if not self.exists():
            return False
        try:
            raw = json.loads(self._meta_path.read_text(encoding="utf-8"))
            meta = StoreMeta(
                model_key=raw["model_key"], model_name=raw["model_name"], dim=int(raw["dim"]),
                count=int(raw.get("count", 0)), dtype=raw.get("dtype", "float32"),
                normalized=bool(raw.get("normalized", True)), version=int(raw.get("version", 1)),
                capacity=int(raw.get("capacity", 0)),
            )
            matrix = self._read_matrix()
            capacity = meta.capacity or int(matrix.shape[0])
            meta.capacity = capacity
            # v1 -> v2 migration: ids/hashes (if any) live in meta.json.
            if "ids" in raw or not self._ids_path.exists() or not self._hashes_path.exists():
                ids = [int(i) for i in raw.get("ids", [])]
                hashes = [str(h) for h in raw.get("content_hashes", [])]
                if len(ids) != meta.count:
                    raise EmbeddingStoreError("legacy meta id/count mismatch")
                self._write_sidecars(ids, hashes, capacity)
                meta.version = STORE_VERSION
                self.meta = meta
                self._write_meta()
            if meta.version != STORE_VERSION:
                raise EmbeddingStoreError(f"unsupported store version {meta.version}")
            self._load_sidecars_into_meta(meta)
            self._validate(matrix, meta, capacity)
            self.meta, self.matrix = meta, matrix[: meta.count]
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Embedding store corrupt/unreadable ({self.dir}): {exc}")
            self.matrix, self.meta, self._ids_arr = None, None, None
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
        if len(set(meta.ids)) != meta.count:
            # Duplicate ids indicate a corrupted/inflated count or sidecar.
            raise EmbeddingStoreError("duplicate ids in store")
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

    # -- save / grow -------------------------------------------------------
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
        self.dir.mkdir(parents=True, exist_ok=True)
        buf = np.lib.format.open_memmap(self._matrix_path, mode="w+", dtype=np.float32,
                                        shape=(capacity, self.dim))
        if len(ids):
            buf[: len(ids)] = matrix
        buf.flush()
        del buf
        self._write_sidecars(ids, content_hashes, capacity)
        self.meta = StoreMeta(
            model_key=self.model_key, model_name=self.model_name, dim=self.dim,
            count=len(ids), ids=ids, content_hashes=content_hashes, capacity=capacity,
        )
        self._write_meta()
        self.matrix = matrix
        self._ids_arr = np.asarray(ids, dtype=np.int64)

    def _ensure_capacity(self, target: int) -> None:
        assert self.meta is not None
        capacity = self.meta.capacity or self.meta.count
        if target <= capacity:
            self.meta.capacity = capacity
            return
        new_capacity = max(target, capacity * 2, _MIN_CAPACITY)
        count = self.meta.count
        old_m = self._read_matrix()
        old_i = self._read_ids()
        old_h = self._read_hashes()
        tmp_m = self._matrix_path.with_suffix(".npy.tmp")
        tmp_i = self._ids_path.with_suffix(".npy.tmp")
        tmp_h = self._hashes_path.with_suffix(".npy.tmp")
        new_m = np.lib.format.open_memmap(tmp_m, mode="w+", dtype=np.float32, shape=(new_capacity, self.dim))
        new_i = np.lib.format.open_memmap(tmp_i, mode="w+", dtype=np.int64, shape=(new_capacity,))
        new_h = np.lib.format.open_memmap(tmp_h, mode="w+", dtype=f"S{_HASH_BYTES}", shape=(new_capacity,))
        if count:
            new_m[:count] = old_m[:count]
            new_i[:count] = old_i[:count]
            new_h[:count] = old_h[:count]
        for buf in (new_m, new_i, new_h):
            buf.flush()
        del new_m, new_i, new_h
        os.replace(tmp_m, self._matrix_path)
        os.replace(tmp_i, self._ids_path)
        os.replace(tmp_h, self._hashes_path)
        self.meta.capacity = new_capacity

    # -- incremental -------------------------------------------------------
    def append(self, ids: Iterable[int], matrix: np.ndarray, hashes: Iterable[str] | None = None) -> None:
        """Incrementally upsert rows (replacing existing ids) in place.

        O(rows added/changed) for the vector, id and hash writes; only small
        scalar metadata is rewritten. ``hashes`` is the per-row content version
        the semantic layer uses to detect changed content.
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

        mbuf = self._open_matrix_rw()
        ibuf = self._open_ids_rw()
        hbuf = self._open_hashes_rw()
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
            mbuf[row] = vec
            ibuf[row] = doc_id
            hbuf[row] = self._enc_hash(chash)
        for buf in (mbuf, ibuf, hbuf):
            buf.flush()
        del mbuf, ibuf, hbuf
        self._write_meta()
        self.matrix = self._read_matrix()[: self.meta.count]
        self._ids_arr = self._read_ids()

    def _compact(self, capacity: int) -> None:
        """Rewrite matrix/ids/hashes at a right-sized capacity (atomic replace).

        Rows must already be compacted to the front. Used after heavy pruning so
        a shrunk corpus does not keep its historical peak allocation forever.
        """
        assert self.meta is not None
        capacity = max(int(capacity), self.meta.count, _MIN_CAPACITY)
        count = self.meta.count
        old_m = self._read_matrix()
        old_i = self._read_ids()
        old_h = self._read_hashes()
        tmp_m = self._matrix_path.with_suffix(".npy.tmp")
        tmp_i = self._ids_path.with_suffix(".npy.tmp")
        tmp_h = self._hashes_path.with_suffix(".npy.tmp")
        new_m = np.lib.format.open_memmap(tmp_m, mode="w+", dtype=np.float32, shape=(capacity, self.dim))
        new_i = np.lib.format.open_memmap(tmp_i, mode="w+", dtype=np.int64, shape=(capacity,))
        new_h = np.lib.format.open_memmap(tmp_h, mode="w+", dtype=f"S{_HASH_BYTES}", shape=(capacity,))
        if count:
            new_m[:count] = old_m[:count]
            new_i[:count] = old_i[:count]
            new_h[:count] = old_h[:count]
        for buf in (new_m, new_i, new_h):
            buf.flush()
        del new_m, new_i, new_h
        os.replace(tmp_m, self._matrix_path)
        os.replace(tmp_i, self._ids_path)
        os.replace(tmp_h, self._hashes_path)
        self.meta.capacity = capacity
        self._write_meta()
        self.matrix = self._read_matrix()[: self.meta.count]
        self._ids_arr = self._read_ids()

    def _prune_rows(self, drop) -> int:
        """Remove rows for which ``drop(doc_id)`` is true, then compact.

        When the surviving count falls below a quarter of the reserved capacity
        the files are right-sized. Returns the number of removed rows.
        """
        if (self.matrix is None or self.meta is None) and not self.load():
            return 0
        if len(self.meta.content_hashes) != self.meta.count:
            self.meta.content_hashes = [""] * self.meta.count
        rows = [r for r, doc_id in enumerate(self.meta.ids) if not drop(doc_id)]
        removed = self.meta.count - len(rows)
        if removed <= 0:
            return 0
        mbuf = self._open_matrix_rw()
        ibuf = self._open_ids_rw()
        hbuf = self._open_hashes_rw()
        if removed:
            idx = np.asarray(rows, dtype=np.int64)
            mbuf[: len(rows)] = mbuf[idx]
            ibuf[: len(rows)] = ibuf[idx]
            hbuf[: len(rows)] = hbuf[idx]
        for buf in (mbuf, ibuf, hbuf):
            buf.flush()
        del mbuf, ibuf, hbuf
        self.meta.ids = [self.meta.ids[r] for r in rows]
        self.meta.content_hashes = [self.meta.content_hashes[r] for r in rows]
        self.meta.count = len(self.meta.ids)
        capacity = int(self.meta.capacity or self.meta.count)
        target = self.meta.count + max(1024, self.meta.count // 10)
        if self.meta.count <= capacity // 4 and capacity > max(_MIN_CAPACITY, self.meta.count * 2):
            self._compact(target)
        else:
            self._write_meta()
            self.matrix = self._read_matrix()[: self.meta.count]
            self._ids_arr = self._read_ids()
        return removed

    def prune(self, keep_ids: Iterable[int]) -> int:
        """Drop rows whose ids are not in ``keep_ids``; returns removed count."""
        keep = {int(i) for i in keep_ids}
        return self._prune_rows(lambda doc_id: doc_id not in keep)

    def remove(self, ids: Iterable[int]) -> int:
        """Drop the given ids (O(removed + store scan)); returns removed count."""
        drop = {int(i) for i in ids}
        if not drop:
            return 0
        return self._prune_rows(lambda doc_id: doc_id in drop)

    # -- query -------------------------------------------------------------
    def search(self, query: np.ndarray, top_k: int = 10) -> list[tuple[int, float]]:
        """Cosine top-k against the pre-normalized matrix (single matvec)."""
        if self.matrix is None or self.meta is None or not self.meta.count or top_k <= 0:
            return []
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        if q.shape[0] != self.dim:
            raise EmbeddingStoreError(f"query dim {q.shape[0]} != store dim {self.dim}")
        norm = float(np.linalg.norm(q))
        if norm == 0.0:
            return []
        scores = (self.matrix @ (q / norm)).astype(np.float32)
        ids = self._ids_arr[: self.meta.count] if self._ids_arr is not None else np.asarray(self.meta.ids)
        k = min(int(top_k), len(scores))
        order = np.lexsort((ids, -scores))[:k]
        return [(int(ids[j]), float(scores[j])) for j in order]

    def stats(self) -> dict:
        def size_of(p: Path) -> int:
            return p.stat().st_size if p.exists() else 0
        return {
            "model_key": self.model_key,
            "dim": self.dim,
            "count": int(self.meta.count) if self.meta else 0,
            "capacity": int(self.meta.capacity) if self.meta else 0,
            "disk_bytes": size_of(self._matrix_path) + size_of(self._ids_path) + size_of(self._hashes_path),
            "ram_bytes": int(self.matrix.nbytes) if self.matrix is not None else 0,
        }
