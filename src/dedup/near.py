"""Explainable near-duplicate discovery.

Candidate generation is bounded and non-quadratic:

* when the embedding store is available, 64/128-bit **random-hyperplane LSH**
  over the semantic vectors generates candidates (cosine-preserving), then each
  candidate is confirmed by exact cosine;
* otherwise a lexical **SimHash + LSH** fallback is used.

Exact duplicates (identical stored content hash) are always excluded, and each
pair carries its semantic and lexical score with a reason category.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

import numpy as np
from loguru import logger

from ..intelligence.embedding_store import EmbeddingMatrixStore
from .fingerprint import band_keys, jaccard, simhash64, tokenize
from .store import DedupStore, _like_prefix

_LSH_SEED = 20260101
_BITS = 128
_BANDS = 8


class NearDuplicateEngine:
    def __init__(self, db, store: Optional[DedupStore] = None,
                 embed_store: Optional[EmbeddingMatrixStore] = None) -> None:
        self.db = db
        self.store = store or DedupStore(db)
        self.embed_store = embed_store

    # -- inputs ------------------------------------------------------------
    def _load_embed_store(self) -> Optional[EmbeddingMatrixStore]:
        if self.embed_store is None:
            return None
        if self.embed_store.matrix is None and not self.embed_store.load():
            return None
        return self.embed_store

    def _active_ids(self, *, min_chars: int, scope_prefix: Optional[str],
                    max_docs: Optional[int]) -> list[int]:
        sql = ("SELECT id FROM files WHERE content_extracted=1 AND content_text IS NOT NULL "
               "AND length(content_text) >= ? AND COALESCE(state,'ACTIVE')='ACTIVE'")
        params: list[Any] = [int(min_chars)]
        if scope_prefix:
            sql += " AND path LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(scope_prefix))
        sql += " ORDER BY id ASC"
        if max_docs:
            sql += " LIMIT ?"
            params.append(int(max_docs))
        with self.db.get_connection() as conn:
            return [int(r[0]) for r in conn.execute(sql, params).fetchall()]

    # -- candidate generation ---------------------------------------------
    def _vector_pairs(self, estore: EmbeddingMatrixStore, ids: list[int], *,
                      bits: int, bands: int, max_pairs: int) -> tuple[list[tuple[int, int]], bool]:
        id_to_row = {int(i): r for r, i in enumerate(estore.meta.ids)}
        sub_ids = [i for i in ids if i in id_to_row]
        if len(sub_ids) < 2:
            return [], False
        matrix = np.asarray(estore.matrix, dtype=np.float32)[[id_to_row[i] for i in sub_ids]]
        dim = matrix.shape[1]
        rng = np.random.default_rng(_LSH_SEED)
        projection = rng.standard_normal((dim, bits)).astype(np.float32)
        signs = (matrix @ projection) > 0  # (n, bits)
        width = bits // bands
        packed = signs.reshape(len(sub_ids), bands, width)
        weights = (1 << np.arange(width)).astype(np.int64)
        keys = packed.astype(np.int64) @ weights  # (n, bands)

        buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for row, fid in enumerate(sub_ids):
            for b in range(bands):
                buckets[(b, int(keys[row, b]))].append(fid)
        pairs: set[tuple[int, int]] = set()
        truncated = False
        for ids_in_bucket in buckets.values():
            if len(ids_in_bucket) < 2:
                continue
            ids_sorted = sorted(ids_in_bucket)
            for i in range(len(ids_sorted)):
                for j in range(i + 1, len(ids_sorted)):
                    pairs.add((ids_sorted[i], ids_sorted[j]))
                    if len(pairs) >= max_pairs:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
        return sorted(pairs), truncated

    def _lexical_pairs(self, ids: list[int], *, bands: int, max_pairs: int) -> tuple[list[tuple[int, int]], bool]:
        fingerprints: dict[int, int] = {}
        with self.db.get_connection() as conn:
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                ph = ",".join("?" * len(chunk))
                for fid, text in conn.execute(
                        f"SELECT id, content_text FROM files WHERE id IN ({ph})", chunk):
                    toks = tokenize(text or "")
                    if len(toks) >= 3:
                        fingerprints[int(fid)] = simhash64(toks)
        buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for fid, fp in fingerprints.items():
            for b, key in enumerate(band_keys(fp, bands=bands)):
                buckets[(b, key)].append(fid)
        pairs: set[tuple[int, int]] = set()
        truncated = False
        for ids_in_bucket in buckets.values():
            if len(ids_in_bucket) < 2:
                continue
            s = sorted(ids_in_bucket)
            for i in range(len(s)):
                for j in range(i + 1, len(s)):
                    pairs.add((s[i], s[j]))
                    if len(pairs) >= max_pairs:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
        return sorted(pairs), truncated

    # -- build -------------------------------------------------------------
    def build(self, *, threshold: float = 0.9, min_chars: int = 200,
              scope_prefix: Optional[str] = None, max_docs: Optional[int] = None,
              max_pairs: int = 2_000_000, bands: int = _BANDS, bits: int = _BITS,
              max_neighbors_per_doc: int = 20) -> dict[str, Any]:
        self.store.prune_missing_relations()
        ids = self._active_ids(min_chars=min_chars, scope_prefix=scope_prefix, max_docs=max_docs)
        estore = self._load_embed_store()
        used_vector = estore is not None and estore.meta is not None and estore.matrix is not None
        if used_vector:
            pairs, truncated = self._vector_pairs(estore, ids, bits=bits, bands=bands, max_pairs=max_pairs)
        else:
            pairs, truncated = self._lexical_pairs(ids, bands=bands, max_pairs=max_pairs)

        hash_by_id = dict(estore.hash_map()) if used_vector else {}
        # Fall back to the persisted exact-content hashes when the embedding store
        # was built without per-row hashes (legacy stores).
        with self.db.get_connection() as conn:
            for fid, digest in conn.execute(
                    "SELECT file_id, digest FROM content_hashes WHERE state='OK' AND digest IS NOT NULL"):
                hash_by_id.setdefault(int(fid), f"sha256:{digest}")
        row_by_id: dict[int, int] = {}
        if used_vector:
            row_by_id = {int(i): r for r, i in enumerate(estore.meta.ids)}

        edges: list[dict[str, Any]] = []
        for a, b in pairs:
            # Exact duplicates are excluded from near-duplicate output.
            if hash_by_id.get(a) and hash_by_id.get(a) == hash_by_id.get(b):
                continue
            sem = None
            if used_vector and a in row_by_id and b in row_by_id:
                sem = float(np.dot(estore.matrix[row_by_id[a]], estore.matrix[row_by_id[b]]))
            if sem is not None and sem < threshold:
                continue
            edges.append({"src_id": a, "dst_id": b,
                          "semantic_score": round(sem, 5) if sem is not None else None,
                          "lexical_score": None,
                          "reason": "semantic" if sem is not None else "candidate"})
        # Lexical score for explanation, computed only for surviving candidates.
        if edges:
            involved = sorted({e["src_id"] for e in edges} | {e["dst_id"] for e in edges})
            tokens: dict[int, set] = {}
            with self.db.get_connection() as conn:
                for start in range(0, len(involved), 500):
                    chunk = involved[start:start + 500]
                    ph = ",".join("?" * len(chunk))
                    for fid, text in conn.execute(
                            f"SELECT id, content_text FROM files WHERE id IN ({ph})", chunk):
                        tokens[int(fid)] = set(tokenize(text or ""))
            for e in edges:
                e["lexical_score"] = round(jaccard(tokens.get(e["src_id"], ()),
                                                   tokens.get(e["dst_id"], ())), 5)
                if e["semantic_score"] is not None and e["lexical_score"] >= 0.6:
                    e["reason"] = "semantic+lexical"
        edges.sort(key=lambda e: (e.get("semantic_score") or 0.0, e.get("lexical_score") or 0.0),
                   reverse=True)
        if max_neighbors_per_doc and max_neighbors_per_doc > 0:
            # Keep the strongest bounded neighbourhood per document so a single
            # huge duplicate cluster cannot blow up the graph or the UI.
            degree: dict[int, int] = defaultdict(int)
            kept = []
            for e in edges:
                if degree[e["src_id"]] >= max_neighbors_per_doc or degree[e["dst_id"]] >= max_neighbors_per_doc:
                    continue
                degree[e["src_id"]] += 1
                degree[e["dst_id"]] += 1
                kept.append(e)
            edges = kept
        saved = self.store.replace_near_duplicates(edges)
        result = {
            "docs": len(ids), "candidate_pairs": len(pairs), "truncated": truncated,
            "near_duplicate_edges": saved, "threshold": threshold,
            "candidate_source": "vector_lsh" if used_vector else "lexical_simhash",
            "embedded_confirmed": sum(1 for e in edges if e["semantic_score"] is not None),
            "bands": bands, "bits": bits, "max_neighbors_per_doc": max_neighbors_per_doc,
        }
        logger.info(f"near-duplicate build: {result}")
        return result

    def neighbors(self, file_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        edges = self.store.near_duplicates_for(file_id, limit=limit)
        ids = [e["other_id"] for e in edges]
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        with self.db.get_connection() as conn:
            docs = {int(r["id"]): dict(r) for r in conn.execute(
                f"SELECT id, path, filename, extension, size_bytes, document_kind, "
                f"COALESCE(state,'ACTIVE') AS state, modified_at FROM files WHERE id IN ({ph})",
                ids).fetchall()}
        out = []
        for e in edges:
            doc = docs.get(e["other_id"])
            if doc is None:
                continue
            doc.update({"semantic_score": e.get("semantic_score"),
                        "lexical_score": e.get("lexical_score"),
                        "reason": e.get("reason"), "relation": "near_duplicate"})
            out.append(doc)
        return out
