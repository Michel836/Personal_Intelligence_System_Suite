"""Related-document suggestions built on the existing embedding store.

Suggestions only: nothing is grouped or moved. Self is always excluded, missing
documents are hidden unless explicitly requested, and each result carries a
reason category (semantic, exact duplicate, near duplicate, version, archive).
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from ..intelligence.embedding_store import EmbeddingMatrixStore
from .store import DedupStore


class RelatedDocuments:
    def __init__(self, db, *, dedup_store: Optional[DedupStore] = None,
                 embed_store: Optional[EmbeddingMatrixStore] = None) -> None:
        self.db = db
        self.store = dedup_store or DedupStore(db)
        self.embed_store = embed_store

    def _load(self) -> Optional[EmbeddingMatrixStore]:
        if self.embed_store is None:
            return None
        if self.embed_store.matrix is None and not self.embed_store.load():
            return None
        return self.embed_store

    def _markers(self, file_id: int) -> dict[str, Any]:
        markers: dict[str, Any] = {}
        h = self.store.get_hash(file_id)
        if h and h.get("digest"):
            markers["exact_group_key"] = f"sha256:{h['digest']}"
        near = self.store.near_duplicates_for(file_id, limit=1)
        if near:
            markers["near_duplicate"] = True
        fam = self.store.get_version_family_for_file(file_id)
        if fam:
            markers["version_family_id"] = fam["id"]
        return markers

    def related(self, file_id: int, *, limit: int = 10, include_missing: bool = False,
                exclude_ids: Optional[set] = None) -> list[dict[str, Any]]:
        estore = self._load()
        if estore is None or estore.meta is None or estore.matrix is None:
            return []
        ids = list(estore.meta.ids)
        try:
            row = ids.index(int(file_id))
        except ValueError:
            return []
        query = estore.matrix[row]
        scores = estore.matrix @ query
        order = np.argsort(-scores)
        exclude = set(exclude_ids or ())
        exclude.add(int(file_id))
        picked: list[tuple] = []
        for idx in order:
            if len(picked) >= limit * 3:
                break
            cand = int(ids[int(idx)])
            if cand in exclude:
                continue
            picked.append((cand, float(scores[int(idx)])))
        if not picked:
            return []
        cand_ids = [c for c, _ in picked]
        ph = ",".join("?" * len(cand_ids))
        state_clause = "" if include_missing else " AND COALESCE(state,'ACTIVE')='ACTIVE'"
        with self.db.get_connection() as conn:
            docs = {int(r["id"]): dict(r) for r in conn.execute(
                f"SELECT id, path, filename, extension, size_bytes, document_kind, "
                f"COALESCE(state,'ACTIVE') AS state, modified_at, archive_parent_id "
                f"FROM files WHERE id IN ({ph}){state_clause}", cand_ids).fetchall()}
        out = []
        for cid, score in picked:
            doc = docs.get(cid)
            if doc is None:
                continue
            doc.update({"semantic_similarity": round(score, 5), "relation": "related",
                        "reason": "semantic"})
            if doc["document_kind"] == "ARCHIVE_MEMBER":
                doc["reason"] = "semantic+archive"
            out.append(doc)
            if len(out) >= limit:
                break
        return out
