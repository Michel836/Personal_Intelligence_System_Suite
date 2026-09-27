"""Incremental document-intelligence pipeline (M015).

Processes only content-bearing documents whose extracted text changed (or that
have never been processed). Language, entities, categories and PII are written
per document; removed content is pruned. No per-document LLM call and no
full-corpus recomputation for a single change.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from .categories import CategoryEngine
from .entities import extract_entities
from .language import detect_language
from .pii import detect_pii
from .store import IntelStore

# NLP is bounded per document so a pathological multi-megabyte text file cannot
# monopolise the pipeline.
MAX_NLP_CHARS = 100_000
MAX_LANGUAGE_CHARS = 20_000
_BATCH = 200


class IntelPipeline:
    def __init__(self, db: Any, *, store: IntelStore | None = None,
                 taxonomy_path: Path | None = None,
                 embedding_gen: Any = None, embed_store: Any = None) -> None:
        self.db = db
        self.store = store or IntelStore(db)
        self.categories = CategoryEngine(taxonomy_path)
        self.embedding_gen = embedding_gen
        self.embed_store = embed_store
        self._category_vectors_cache: dict[str, Any] | None = None
        self._id_to_row: dict[int, int] | None = None

    # -- semantic category vectors (optional) -----------------------------
    def _category_vectors(self) -> dict[str, Any] | None:
        if self.embedding_gen is None or self.embed_store is None:
            return None
        if self._category_vectors_cache is not None:
            return self._category_vectors_cache
        try:
            if self.embed_store.matrix is None:
                self.embed_store.load()
            vectors = {}
            for cat in self.categories.categories:
                text = cat.get("description") or cat["name"]
                vec = self.embedding_gen.generate_embedding(text)
                if vec is not None:
                    vectors[cat["name"]] = vec
            self._category_vectors_cache = vectors or None
        except Exception as exc:  # noqa: BLE001 - semantic categories are optional
            logger.debug(f"category vectors unavailable: {exc}")
            self._category_vectors_cache = None
        return self._category_vectors_cache

    def _doc_vector(self, file_id: int) -> Any:
        if self.embed_store is None or self.embed_store.meta is None or self.embed_store.matrix is None:
            return None
        if self._id_to_row is None:
            self._id_to_row = {int(i): r for r, i in enumerate(self.embed_store.meta.ids)}
        row = self._id_to_row.get(int(file_id))
        return None if row is None else self.embed_store.matrix[row]

    # -- single document ---------------------------------------------------
    def _detect(self, file_id: int, text: str, *, extension: str | None,
                overrides: dict[str, bool] | None = None) -> tuple[Any, ...]:
        text = (text or "")[:MAX_NLP_CHARS]
        lang = detect_language(text[:MAX_LANGUAGE_CHARS])
        entities = extract_entities(text, store=self.store)
        cat_vec = self._doc_vector(file_id)
        cats = self.categories.classify(text, extension=extension,
                                        doc_vector=cat_vec, category_vectors=self._category_vectors())
        cats = self._apply_overrides(file_id, cats, overrides)
        findings = detect_pii(text, store=self.store)
        return text, lang, entities, cats, findings

    def process_document(self, file_id: int, text: str, *, extension: str | None = None,
                         source_indexed_at: str | None = None) -> dict[str, Any]:
        used_text, lang, entities, cats, findings = self._detect(
            file_id, text, extension=extension, overrides=self.store.overrides_for(file_id))
        self.store.save_document_intel(
            file_id, language=lang, entities=entities, categories=cats, pii=findings,
            source_indexed_at=source_indexed_at, content_len=len(text or ""),
        )
        return {"file_id": file_id, "language": lang["lang"], "language_status": lang["status"],
                "entities": len(entities), "categories": len(cats), "pii": len(findings)}

    def _apply_overrides(self, file_id: int, categories: list[dict[str, Any]],
                         overrides: dict[str, bool] | None = None) -> list[dict[str, Any]]:
        if overrides is None:
            overrides = self.store.overrides_for(file_id)
        if not overrides:
            return categories
        by_name = {c["category"]: dict(c) for c in categories}
        for name, include in overrides.items():
            if include:
                by_name[name] = {"category": name, "score": 1.0, "source": "manual"}
            else:
                by_name.pop(name, None)
        return sorted(by_name.values(), key=lambda c: (c["source"] == "manual", c["score"]), reverse=True)

    # -- batch -------------------------------------------------------------
    def run(self, *, limit: int | None = None, scope_prefix: str | None = None,
            min_chars: int = 20, include_members: bool = False, force: bool = False,
            progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        docs = self.store.stale_documents(scope_prefix=scope_prefix, min_chars=min_chars,
                                          include_members=include_members, limit=limit, force=force)
        stats: dict[str, Any] = {"candidates": len(docs), "processed": 0, "languages": 0, "pii_docs": 0}
        t0 = time.perf_counter()
        all_overrides = self.store.all_overrides()
        batch: list[Any] = []

        def flush(conn: Any) -> None:
            for item in batch:
                self.store.write_document_intel(conn, item[0], language=item[2], entities=item[3],
                                                categories=item[4], pii=item[5],
                                                source_indexed_at=item[6], content_len=item[7])
            conn.commit()
            batch.clear()

        for i, doc in enumerate(docs):
            fid = int(doc["id"])
            path = doc.get("path") or ""
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else None
            used_text, lang, entities, cats, findings = self._detect(
                fid, doc.get("content_text") or "", extension=ext,
                overrides=all_overrides.get(fid))
            batch.append((fid, None, lang, entities, cats, findings,
                          doc.get("source_indexed_at"), int(doc.get("content_len") or len(used_text))))
            stats["processed"] += 1
            if findings:
                stats["pii_docs"] += 1
            if len(batch) >= _BATCH:
                with self.db.get_connection() as conn:
                    flush(conn)
            if progress and (i + 1) % 200 == 0:
                progress(i + 1, len(docs))
        if batch:
            with self.db.get_connection() as conn:
                flush(conn)
        wall = time.perf_counter() - t0
        stats["wall_s"] = round(wall, 3)
        stats["docs_per_sec"] = round(stats["processed"] / wall, 1) if wall else 0
        stats["pruned"] = self.store.prune_removed()
        logger.info(f"intel pipeline: {stats}")
        return stats

    # -- read --------------------------------------------------------------
    def get_document(self, file_id: int) -> dict[str, Any]:
        return {"language": self.store.get_language(file_id),
                "categories": self.store.get_categories(file_id),
                "entities": self.store.get_entities(file_id),
                "pii": self.store.get_pii(file_id)}
