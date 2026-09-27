"""Semantic search engine using embeddings."""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import hashlib
import json
import os
from functools import lru_cache
from cachetools import LRUCache
import threading

from loguru import logger
from ..core.database import DatabaseManager
from ..core.perf_config import get_resource_config
from ..core.validation import validate_semantic_search_params, SemanticSearchParams, ValidationError
from .embeddings import EmbeddingGenerator, EmbeddingGenerationError


class SemanticSearchEngine:
    """Semantic search engine for intelligent document retrieval."""
    
    def __init__(self, db: Optional[DatabaseManager] = None, embedding_gen=None):
        self.db = db or DatabaseManager()
        self.embedding_gen = embedding_gen if embedding_gen is not None else self._resolve_embedding_generator()
        
        # LRU cache for embeddings (max 10,000 embeddings ~ 1GB memory)
        self.embeddings_cache = LRUCache(maxsize=10000)
        self.cache_lock = threading.Lock()
        
        # Query cache for search results (max 1000 queries ~ 100MB)
        self.query_cache = LRUCache(maxsize=1000)
        self.query_cache_lock = threading.Lock()

        # Persistent pre-normalized embedding matrix (M009I.1).
        self._store = None
        # Serialises refresh + store reads so concurrent semantic queries and
        # concurrent extraction/refresh cannot observe a half-updated matrix.
        self._store_lock = threading.RLock()

        logger.info(f"SemanticSearchEngine initialized. Embeddings available: {self.embedding_gen.is_available()}")

    @staticmethod
    def _resolve_embedding_generator():
        """Return the configured embedding generator.

        The proven local ``EmbeddingGenerator`` is used unless the router selects
        a *remote* embedding provider (PIS_AI_MODE/PIS_EMBEDDING_BACKEND +
        PIS_API_* + a policy that permits extracted text). This keeps the local
        store namespace and behaviour unchanged by default.
        """
        try:
            from ..ai.providers.service import get_ai_service

            override = get_ai_service().remote_embedding_generator()
            if override is not None:
                return override
        except Exception as exc:  # noqa: BLE001 - degrade to the local path
            logger.debug(f"AI service unavailable, using local embeddings: {exc}")
        return EmbeddingGenerator()

    def _get_store(self) -> Any:
        """Return the persistent matrix store for the active embedding model."""
        from .embedding_store import EmbeddingMatrixStore

        key = getattr(self.embedding_gen, "model_key", type(self.embedding_gen).__name__)
        name = getattr(self.embedding_gen, "model_name", key)
        dim = int(getattr(self.embedding_gen, "embedding_dim", 0) or 0)
        base = os.environ.get("PIS_EMBEDDING_STORE_DIR")
        if self._store is None or self._store.model_key != key or self._store.dim != dim:
            self._store = EmbeddingMatrixStore(
                key, name, dim, base_dir=Path(base) if base else None
            )
        return self._store

    def _embed_texts(self, texts):
        if not texts:
            return []
        batch_size = int(os.environ.get("PIS_EMBEDDING_BATCH_SIZE", "0")) or get_resource_config().embedding_batch_size
        return self.embedding_gen.generate_batch_embeddings(
            texts, batch_size=batch_size, show_progress=False
        )

    @staticmethod
    def _content_hash(text: str) -> str:
        """Stable fingerprint of extracted content (detects changed documents)."""
        return hashlib.blake2b(text.encode("utf-8", "ignore"), digest_size=16).hexdigest()

    def _apply_prune(self, store, batch_size: int) -> int:
        """Remove store rows for pruned/missing/content-less documents."""
        total = 0
        # Compaction is O(store) per call, so use a larger prune batch to keep
        # the number of passes small even for large deletions.
        prune_batch = max(int(batch_size), 4096)
        while True:
            ids = self.db.semantic_prune_batch(limit=prune_batch)
            if not ids:
                break
            store.remove(ids)
            self.db.mark_semantic_pruned(ids)
            total += len(ids)
            if len(ids) < prune_batch:
                break
        return total

    def _refresh_semantic(self, store, *, model_key: str, dim: int, batch_size: int = 256):
        """Bring the store up to date with the dirty/prune set only.

        Complexity is O(changed + pruned), not O(corpus): the DB yields only
        rows whose semantic source changed. Clean marks are written *after* the
        store write, so a crash mid-refresh leaves rows pending and the next
        refresh converges (at-least-once, idempotent).
        """
        if store.matrix is None and store.meta is None and not store.load():
            # Missing/corrupt store: every tracked vector must be rebuilt.
            self.db.reset_semantic_for_rebuild()
        if self.db.semantic_sweep_due():
            # Rare O(corpus) reconciliation restores the dirty/prune flags after
            # scans/archive changes; hot queries stay O(pending).
            self.db.reconcile_semantic_state()
        total_pruned = self._apply_prune(store, batch_size)
        total_embedded = 0
        while True:
            dirty = self.db.semantic_dirty_batch(model_key=model_key, dim=dim, limit=batch_size)
            if not dirty:
                break
            versions = []
            for row in dirty:
                content = (row.get("content_text") or "").strip()
                if content:
                    versions.append((int(row["id"]), content, self._content_hash(content)))
            if not versions:
                # Dirty rows without usable content cannot be embedded.
                self.db.mark_semantic_pruned([int(r["id"]) for r in dirty])
                total_pruned += len(dirty)
                continue
            embeddings = self._embed_texts([c for _, c, _ in versions])
            ids, matrix, entries = [], [], []
            for (fid, _content, ver), emb in zip(versions, embeddings, strict=False):
                if emb is None:
                    continue
                ids.append(fid)
                matrix.append(emb)
                entries.append((fid, ver))
            if not entries:
                # Embedding produced nothing usable for this batch. Do not spin
                # forever: surface it explicitly and leave rows dirty for retry.
                logger.error(
                    "semantic refresh made no progress on %d dirty row(s); aborting this pass",
                    len(dirty),
                )
                break
            store.append(ids, np.vstack(matrix), hashes=[v for _, v in entries])
            self.db.mark_semantic_embedded(entries, model_key=model_key, dim=dim)
            total_embedded += len(entries)
            if len(dirty) < batch_size:
                break
        return total_embedded, total_pruned

    def _refresh_store(self, store, documents):
        """Low-level explicit-list upsert (benchmarks/legacy callers only).

        Production search uses :meth:`_refresh_semantic`. This path rebuilds or
        appends for an explicit document list without consulting dirty state.
        """
        valid = []
        id_map = {}
        hashes = {}
        for doc in documents:
            content = (doc.get("content_text") or "").strip()
            if content:
                doc_id = int(doc["id"])
                valid.append((doc_id, content))
                id_map[doc_id] = doc
                hashes[doc_id] = self._content_hash(content)
        if store.matrix is None or store.meta is None:
            loaded = store.load()
        else:
            loaded = True
        if not loaded:
            embeddings = self._embed_texts([t for _, t in valid])
            pairs = [(i, e, hashes[i]) for (i, _), e in zip(valid, embeddings, strict=False) if e is not None]
            if pairs:
                store.save([i for i, _, _ in pairs], np.vstack([e for _, e, _ in pairs]),
                           hashes=[h for _, _, h in pairs])
            return id_map
        removed = store.prune(set(id_map))
        existing = store.hash_map()
        missing = [(i, t) for i, t in valid if existing.get(i) != hashes[i]]
        if missing:
            embeddings = self._embed_texts([t for _, t in missing])
            pairs = [(i, e, hashes[i]) for (i, _), e in zip(missing, embeddings, strict=False) if e is not None]
            if pairs:
                store.append([i for i, _, _ in pairs], np.vstack([e for _, e, _ in pairs]),
                             hashes=[h for _, _, h in pairs])
        if removed or missing:
            with self.query_cache_lock:
                self.query_cache.clear()
        return id_map

    def is_available(self) -> bool:
        """Check if semantic search is available."""
        return self.embedding_gen.is_available()
    
    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Alias for semantic_search for compatibility."""
        return self.semantic_search(query, limit)

    def refresh(self, *, batch_size: int = 256) -> dict[str, Any]:
        """Bring the persistent store up to date with dirty documents.

        Bounded and idempotent; safe to call repeatedly. Returns an aggregate
        summary (no content). Used by the canonical CLI/API maintenance paths.
        """
        store = self._get_store()
        if not self.is_available():
            return {"available": False, "embedded": 0, "pruned": 0, "store_count": 0}
        embedded, pruned = self._refresh_semantic(
            store, model_key=store.model_key, dim=store.dim, batch_size=int(batch_size))
        store.load()
        return {"available": True, "embedded": int(embedded), "pruned": int(pruned),
                "store_count": int(store.meta.count) if store.meta else 0}
    
    def semantic_search(
        self,
        query: str,
        limit: int = 20,
        similarity_threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """Perform semantic search on document content with validation and caching."""
        
        # Validate parameters
        try:
            params = validate_semantic_search_params(
                query=query,
                limit=limit,
                similarity_threshold=similarity_threshold
            )
        except ValidationError as e:
            logger.error(f"Invalid search parameters: {e}")
            return []
        
        if not self.is_available():
            logger.warning("Semantic search not available - falling back to regular search")
            return self.db.search_files(query=params.query, limit=params.limit)

        from ..ai.providers.base import AIProviderError

        # Refresh only changed documents, then serve from the store under a lock
        # so a concurrent refresh cannot expose a half-updated matrix.
        with self._store_lock:
            try:
                store = self._get_store()
                self._refresh_semantic(store, model_key=store.model_key, dim=store.dim)
            except (AIProviderError, EmbeddingGenerationError) as exc:
                # A provider/embedding failure must degrade to lexical search,
                # never crash the query. Rows stay dirty and are retried later.
                logger.warning(f"semantic refresh unavailable ({exc}); using lexical search")
                return self.db.search_files(query=params.query, limit=params.limit)
            generation = self.db.semantic_generation()
            cache_key = (params.query, params.limit, params.similarity_threshold, generation)
            with self.query_cache_lock:
                cached = self.query_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Found cached results for query: '{params.query}'")
                return cached

            if store.matrix is None or store.meta is None or not store.meta.ids:
                logger.info("No valid document embeddings found")
                return []

            logger.info(f"Performing semantic search for: '{params.query}'")
            query_embedding = self.embedding_gen.generate_embedding(params.query)
            if query_embedding is None:
                logger.error("Failed to generate query embedding")
                return []

            # Overfetch so rows filtered by threshold/lifecycle cannot shrink
            # the returned result count below the requested limit.
            overfetch = max(int(params.limit) * 4, int(params.limit) + 32)
            ranked = store.search(query_embedding, top_k=overfetch)
            docs = {int(d["id"]): d for d in self.db.get_documents_by_ids(
                [doc_id for doc_id, _ in ranked])}
            results = []
            for doc_id, similarity in ranked:
                if len(results) >= params.limit:
                    break
                if similarity >= params.similarity_threshold and doc_id in docs:
                    doc = docs[doc_id].copy()
                    doc['semantic_similarity'] = similarity
                    doc['search_type'] = 'semantic'
                    results.append(doc)

            logger.info(f"Found {len(results)} semantically similar documents")
            with self.query_cache_lock:
                self.query_cache[cache_key] = results
            return results
    
    def hybrid_search(
        self,
        query: str,
        limit: int = 20,
        semantic_weight: float = 0.7,
        text_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """Combine semantic and text search for best results."""
        
        # Get semantic results
        semantic_results = self.semantic_search(query, limit=limit)
        
        # Get text search results
        text_results = self.db.search_files(query=query, limit=limit)
        
        # Combine and deduplicate
        combined_results = {}
        
        # Add semantic results
        for doc in semantic_results:
            doc_id = doc['id']
            score = doc.get('semantic_similarity', 0.0) * semantic_weight
            combined_results[doc_id] = {
                'document': doc,
                'semantic_score': doc.get('semantic_similarity', 0.0),
                'text_score': 0.0,
                'combined_score': score
            }
        
        # Add text results
        for doc in text_results:
            doc_id = doc['id']
            
            # Simple text relevance scoring (can be improved)
            text_score = self._calculate_text_relevance(query, doc)
            
            if doc_id in combined_results:
                # Update existing result
                combined_results[doc_id]['text_score'] = text_score
                combined_results[doc_id]['combined_score'] += text_score * text_weight
            else:
                # Add new result
                combined_results[doc_id] = {
                    'document': doc,
                    'semantic_score': 0.0,
                    'text_score': text_score,
                    'combined_score': text_score * text_weight
                }
        
        # Sort by combined score
        sorted_results = sorted(
            combined_results.values(),
            key=lambda x: x['combined_score'],
            reverse=True
        )
        
        # Format results
        final_results = []
        for result in sorted_results[:limit]:
            doc = result['document'].copy()
            doc.update({
                'semantic_similarity': result['semantic_score'],
                'text_relevance': result['text_score'],
                'combined_score': result['combined_score'],
                'search_type': 'hybrid'
            })
            final_results.append(doc)
        
        logger.info(f"Hybrid search returned {len(final_results)} results")
        return final_results
    
    def find_similar_documents(
        self,
        document_id: int,
        limit: int = 10,
        similarity_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Find documents similar to a given document."""
        
        if not self.is_available():
            return []
        
        # Get the reference document
        ref_doc = self._get_document_by_id(document_id)
        if not ref_doc or not ref_doc.get('content_text'):
            return []
        
        # Get or generate embedding for reference document
        ref_embedding = self._get_cached_embedding(document_id)
        if ref_embedding is None:
            ref_embedding = self.embedding_gen.generate_embedding(ref_doc['content_text'])
            if ref_embedding is None:
                return []
            self._cache_embedding(document_id, ref_embedding)
        
        # Find similar documents
        return self.semantic_search_by_embedding(
            ref_embedding, 
            limit=limit + 1,  # +1 to exclude the reference document
            similarity_threshold=similarity_threshold,
            exclude_id=document_id
        )
    
    def semantic_search_by_embedding(
        self,
        query_embedding: np.ndarray,
        limit: int = 20,
        similarity_threshold: float = 0.3,
        exclude_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Search using a pre-computed embedding."""
        
        documents = self._get_documents_with_content(limit * 3)
        if not documents:
            return []
        
        doc_embeddings = []
        valid_docs = []
        
        for doc in documents:
            doc_id = doc['id']
            
            # Skip excluded document
            if exclude_id and doc_id == exclude_id:
                continue
            
            content = doc.get('content_text', '')
            if not content.strip():
                continue
            
            embedding = self._get_cached_embedding(doc_id)
            if embedding is None:
                embedding = self.embedding_gen.generate_embedding(content)
                if embedding is not None:
                    self._cache_embedding(doc_id, embedding)
            
            if embedding is not None:
                doc_embeddings.append(embedding)
                valid_docs.append(doc)
        
        # Find similar documents
        similar_indices = self.embedding_gen.find_similar(
            query_embedding,
            doc_embeddings,
            top_k=limit
        )
        
        results = []
        for idx, similarity in similar_indices:
            if similarity >= similarity_threshold:
                doc = valid_docs[idx].copy()
                doc['semantic_similarity'] = similarity
                doc['search_type'] = 'semantic'
                results.append(doc)
        
        return results
    
    def _get_documents_with_content(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get documents that have extracted content.

        ``limit=None`` returns the whole corpus (used by semantic search); an
        explicit limit is still available for bounded callers.
        """
        sql = """
            SELECT * FROM files
            WHERE content_extracted = 1
            AND content_text IS NOT NULL
            AND length(content_text) > 50
            AND COALESCE(state, 'ACTIVE') = 'ACTIVE'
            ORDER BY priority DESC, modified_at DESC
        """
        with self.db.get_connection() as conn:
            if limit is None:
                cursor = conn.execute(sql)
            else:
                cursor = conn.execute(sql + " LIMIT ?", (int(limit),))
            return [dict(row) for row in cursor]
    
    def _get_document_by_id(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific document by ID."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM files WHERE id = ?
            """, (doc_id,))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def _calculate_text_relevance(self, query: str, document: Dict[str, Any]) -> float:
        """Calculate text relevance score (simple implementation)."""
        
        content = document.get('content_text') or ''
        filename = document.get('filename') or ''
        
        if not content and not filename:
            return 0.0
        
        query_lower = query.lower()
        content_lower = content.lower() if content else ''
        filename_lower = filename.lower() if filename else ''
        
        score = 0.0
        
        # Filename matches (high weight)
        if query_lower in filename_lower:
            score += 1.0
        
        # Content matches
        content_matches = content_lower.count(query_lower)
        if content_matches > 0:
            # Normalize by content length
            content_length = len(content_lower.split())
            score += min(content_matches / max(content_length, 1) * 10, 1.0)
        
        return score
    
    def _get_cached_embedding(self, doc_id: int) -> Optional[np.ndarray]:
        """Get cached embedding for document (thread-safe)."""
        
        # Check memory cache with lock
        with self.cache_lock:
            if doc_id in self.embeddings_cache:
                return self.embeddings_cache[doc_id]
        
        # Check disk cache
        cache_key = f"doc_{doc_id}"
        embedding = self.embedding_gen.load_embedding_cache(cache_key)
        
        if embedding is not None:
            with self.cache_lock:
                self.embeddings_cache[doc_id] = embedding
        
        return embedding
    
    def _cache_embedding(self, doc_id: int, embedding: np.ndarray) -> None:
        """Cache embedding for document (thread-safe)."""
        
        # Memory cache with lock
        with self.cache_lock:
            self.embeddings_cache[doc_id] = embedding
        
        # Disk cache
        cache_key = f"doc_{doc_id}"
        self.embedding_gen.save_embedding_cache(cache_key, embedding)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get semantic search statistics."""
        
        # Count documents with embeddings
        cached_embeddings = len(self.embeddings_cache)
        
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM files 
                WHERE content_extracted = 1 
                AND content_text IS NOT NULL
            """)
            total_with_content = cursor.fetchone()[0]
        
        return {
            'semantic_search_available': self.is_available(),
            'embedding_model': self.embedding_gen.model_name if self.is_available() else None,
            'embedding_dimension': self.embedding_gen.embedding_dim,
            'cached_embeddings': cached_embeddings,
            'documents_with_content': total_with_content,
            'cache_hit_rate': 0.0  # TODO: implement proper tracking
        }