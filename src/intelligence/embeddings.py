"""Embedding generation for semantic search."""

import os
import numpy as np
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

from loguru import logger

from ..core.perf_config import get_resource_config

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers not available - semantic search disabled")


# Registry of supported embedding models. ``dim`` is only a hint; the actual
# dimension is always read from the loaded model output.
EMBEDDING_MODELS: Dict[str, Dict[str, Any]] = {
    "all-MiniLM-L6-v2": {"hf": "sentence-transformers/all-MiniLM-L6-v2", "dim": 384},
    "multilingual-e5-base": {"hf": "intfloat/multilingual-e5-base", "dim": 768},
    "bge-m3": {"hf": "BAAI/bge-m3", "dim": 1024},
    "qwen3-embedding-0.6b": {"hf": "Qwen/Qwen3-Embedding-0.6B", "dim": 1024},
}
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class EmbeddingGenerationError(RuntimeError):
    """Raised when embeddings cannot be produced even at the minimum batch size.

    The build must not silently return ``None`` for every vector on CUDA OOM:
    it retries with progressively smaller batches first, and only fails
    explicitly once a single-item batch also OOMs.
    """


def resolve_model_key(model_name: Optional[str] = None) -> str:
    """Resolve a model key from an argument, ``PIS_EMBEDDING_MODEL`` or default."""
    import os

    candidate = (model_name or os.environ.get("PIS_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()
    for key, spec in EMBEDDING_MODELS.items():
        if candidate.lower() in (key.lower(), spec["hf"].lower()):
            return key
    # Allow arbitrary HuggingFace ids with an explicit registry entry fallback.
    if "/" in candidate:
        EMBEDDING_MODELS[candidate] = {"hf": candidate, "dim": None}
        return candidate
    raise ValueError(
        f"unknown embedding model {candidate!r}; known: {sorted(EMBEDDING_MODELS)}"
    )


class EmbeddingGenerator:
    """Generate embeddings for semantic search."""
    
    def __init__(self, model_name: Optional[str] = None):
        self.model_key = resolve_model_key(model_name)
        self.model_name = EMBEDDING_MODELS[self.model_key]["hf"]
        self.model = None
        self.embedding_dim = None
        # Set by ``_encode_with_fallback``; useful for diagnostics/tests.
        self.last_effective_batch_size: Optional[int] = None

        # Cache namespaced by model so vectors from different spaces never mix.
        # Honour an explicit path so trials/tests never write into the repo.
        cache_base = os.environ.get("PIS_EMBEDDING_CACHE_DIR")
        self.cache_dir = (Path(cache_base) if cache_base else Path("data/cache/embeddings")) / self.model_key
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        if SENTENCE_TRANSFORMERS_AVAILABLE:
            self._load_model()
        else:
            logger.error("sentence-transformers not installed. Install with: pip install sentence-transformers")
    
    def _load_model(self) -> bool:
        """Load the embedding model."""
        try:
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)
            self._maybe_half()
            
            # Test embedding to get dimension
            test_embedding = self._encode_with_fallback(["test"], batch_size=1)
            self.embedding_dim = int(len(test_embedding[0]))
            self._write_model_metadata()
            
            logger.info(f"Model loaded successfully. Embedding dimension: {self.embedding_dim}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.model = None
            return False

    def _maybe_half(self) -> None:
        """Use fp16 on CUDA when enabled (measured ~2.5-3x throughput)."""
        if self.model is None or not get_resource_config().embedding_fp16:
            return
        try:
            import torch

            if torch.cuda.is_available():
                self.model = self.model.half()
                logger.info("Embedding model running in fp16 on CUDA")
        except Exception as exc:  # pragma: no cover - optional acceleration
            logger.debug(f"fp16 unavailable, using default precision: {exc}")

    def _encode(self, texts: List[str], batch_size: Optional[int] = None) -> np.ndarray:
        """Encode with gradient tracking disabled when torch is available."""
        assert self.model is not None
        kwargs: Dict[str, Any] = {}
        if batch_size is not None:
            kwargs["batch_size"] = batch_size
        try:
            import torch

            with torch.inference_mode():
                return np.asarray(self.model.encode(texts, **kwargs))
        except Exception as exc:  # noqa: BLE001
            # CUDA OOM must reach the adaptive retry, never a blind second try.
            if self._is_cuda_oom(exc):
                raise
            return np.asarray(self.model.encode(texts, **kwargs))

    # -- adaptive CUDA-OOM fallback ---------------------------------------
    MIN_BATCH_SIZE = 1

    @staticmethod
    def _is_cuda_oom(exc: BaseException) -> bool:
        """Return True for CUDA/CuDNN out-of-memory errors (deterministic)."""
        name = type(exc).__name__
        if name in {"OutOfMemoryError", "CudaOutOfMemoryError"}:
            return True
        msg = str(exc).lower()
        return "out of memory" in msg and ("cuda" in msg or "gpu" in msg or "memory" in msg)

    @staticmethod
    def _clear_cuda_cache() -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - best effort only
            pass

    def _encode_with_fallback(
        self, texts: List[str], batch_size: Optional[int] = None
    ) -> "np.ndarray[Any, Any]":
        """Encode one chunk, halving the batch on CUDA OOM down to size 1.

        Raises :class:`EmbeddingGenerationError` when even a single-item batch
        cannot be encoded, so a failure is explicit and never silently skipped.
        """
        requested = int(batch_size or len(texts) or 1)
        batch = max(1, min(requested, len(texts) or 1))
        while True:
            try:
                result = self._encode(texts, batch_size=batch)
                self.last_effective_batch_size = batch
                return result
            except Exception as exc:  # noqa: BLE001
                if not self._is_cuda_oom(exc):
                    raise
                self._clear_cuda_cache()
                if batch <= self.MIN_BATCH_SIZE:
                    raise EmbeddingGenerationError(
                        f"embedding failed at minimum batch size {self.MIN_BATCH_SIZE}: {exc}"
                    ) from exc
                next_batch = max(self.MIN_BATCH_SIZE, batch // 2)
                logger.warning(
                    "CUDA OOM encoding %d texts at batch %d; retrying at batch %d",
                    len(texts), batch, next_batch,
                )
                batch = next_batch
    
    def _write_model_metadata(self) -> None:
        """Persist model provenance next to its embedding cache."""
        try:
            (self.cache_dir / "_model.json").write_text(
                json.dumps({
                    "model_key": self.model_key,
                    "model_name": self.model_name,
                    "embedding_dim": self.embedding_dim,
                }),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug(f"Could not persist model metadata: {exc}")

    def is_available(self) -> bool:
        """Check if embedding generation is available."""
        return self.model is not None
    
    def generate_embedding(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding for a single text."""
        if not self.is_available():
            return None
        
        try:
            # Clean and prepare text
            text = self._prepare_text(text)
            if not text:
                return None
            
            # Generate embedding
            embedding = self._encode_with_fallback([text], batch_size=1)[0]
            return embedding.astype(np.float32)  # Save memory
            
        except Exception as e:
            logger.debug(f"Error generating embedding: {e}")
            return None
    
    def generate_batch_embeddings(
        self, 
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = True
    ) -> List[Optional[np.ndarray]]:
        """Generate embeddings for multiple texts."""
        if not self.is_available():
            return [None] * len(texts)
        
        logger.info(f"Generating embeddings for {len(texts)} texts")
        
        # Prepare texts
        prepared_texts = [self._prepare_text(text) for text in texts]
        
        # Filter out empty texts but keep track of indices
        valid_texts = []
        valid_indices = []
        
        for i, text in enumerate(prepared_texts):
            if text:
                valid_texts.append(text)
                valid_indices.append(i)
        
        if not valid_texts:
            return [None] * len(texts)
        
        # Generate embeddings in batches
        embeddings = []

        for i in range(0, len(valid_texts), batch_size):
            batch = valid_texts[i:i + batch_size]

            if show_progress and i % (batch_size * 5) == 0:
                logger.info(f"Processing batch {i//batch_size + 1}/{(len(valid_texts) + batch_size - 1)//batch_size}")

            batch_embeddings = self._encode_with_fallback(batch, batch_size=batch_size)
            embeddings.extend(batch_embeddings.astype(np.float32))

        # Map back to original indices
        result = [None] * len(texts)
        for i, embedding in enumerate(embeddings):
            original_idx = valid_indices[i]
            result[original_idx] = embedding

        logger.info(f"Generated {len(embeddings)} embeddings successfully")
        return result
    
    def _prepare_text(self, text: str) -> str:
        """Clean and prepare text for embedding."""
        if not text:
            return ""
        
        # Basic cleaning
        text = text.strip()
        
        # Truncate very long texts (models have token limits)
        max_chars = 8000  # Conservative limit
        if len(text) > max_chars:
            text = text[:max_chars]
        
        # Remove excessive whitespace
        text = " ".join(text.split())
        
        return text
    
    def compute_similarity(
        self, 
        embedding1: np.ndarray, 
        embedding2: np.ndarray
    ) -> float:
        """Compute cosine similarity between two embeddings."""
        try:
            # Normalize embeddings
            norm1 = np.linalg.norm(embedding1)
            norm2 = np.linalg.norm(embedding2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            # Cosine similarity
            similarity = np.dot(embedding1, embedding2) / (norm1 * norm2)
            return float(similarity)
            
        except Exception as e:
            logger.debug(f"Error computing similarity: {e}")
            return 0.0
    
    def find_similar(
        self,
        query_embedding: np.ndarray,
        candidate_embeddings: List[np.ndarray],
        top_k: int = 10
    ) -> List[tuple]:
        """Find the most cosine-similar candidates (vectorized).

        Equivalent to the previous per-pair loop but computing all cosine
        similarities in one matrix operation (no per-pair norm recomputation).
        Ranking is deterministic: similarity descending, then original index
        ascending (matching the reference implementation). ``None`` candidates
        are skipped. Returns ``[(index, similarity), ...]``.
        """
        if query_embedding is None or candidate_embeddings is None or top_k <= 0:
            return []
        if isinstance(candidate_embeddings, np.ndarray):
            if candidate_embeddings.size == 0:
                return []
        elif len(candidate_embeddings) == 0:
            return []

        query = np.asarray(query_embedding, dtype=np.float32)
        query_norm = float(np.linalg.norm(query))
        if query_norm == 0.0:
            return []

        if isinstance(candidate_embeddings, np.ndarray):
            # Fast path: pre-stacked matrix avoids the per-call list->matrix copy.
            matrix = np.asarray(candidate_embeddings, dtype=np.float32)
            if matrix.ndim != 2:
                raise ValueError("candidate matrix must be 2-dimensional")
            index_array = np.arange(matrix.shape[0])
        else:
            indices: List[int] = []
            vectors: List[np.ndarray] = []
            for i, candidate in enumerate(candidate_embeddings):
                if candidate is None:
                    continue
                indices.append(i)
                vectors.append(np.asarray(candidate, dtype=np.float32))
            if not vectors:
                return []
            matrix = np.vstack(vectors)
            index_array = np.asarray(indices)

        if matrix.shape[1] != query.shape[0]:
            raise ValueError(
                "embedding dimension mismatch: "
                f"query={query.shape[0]} candidates={matrix.shape[1]}"
            )

        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0.0] = 1e-12
        similarities = (matrix @ query) / (norms * query_norm)

        k = min(int(top_k), len(similarities))
        # lexsort: last key is primary -> (-similarity, index) ascending.
        order = np.lexsort((index_array, -similarities))[:k]
        return [(int(index_array[j]), float(similarities[j])) for j in order]
    
    def save_embedding_cache(self, cache_key: str, embedding: np.ndarray) -> None:
        """Save embedding to cache."""
        try:
            cache_file = self.cache_dir / f"{cache_key}.npy"
            np.save(cache_file, embedding)
        except Exception as e:
            logger.debug(f"Error saving embedding cache: {e}")
    
    def load_embedding_cache(self, cache_key: str) -> Optional[np.ndarray]:
        """Load embedding from cache."""
        try:
            cache_file = self.cache_dir / f"{cache_key}.npy"
            if cache_file.exists():
                return np.load(cache_file)
        except Exception as e:
            logger.debug(f"Error loading embedding cache: {e}")
        
        return None
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        return {
            "model_name": self.model_name,
            "available": self.is_available(),
            "embedding_dimension": self.embedding_dim,
            "max_sequence_length": getattr(self.model, 'max_seq_length', 'Unknown') if self.model else None
        }