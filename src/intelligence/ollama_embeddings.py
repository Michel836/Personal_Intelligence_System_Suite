"""Ollama embeddings for semantic search."""

import numpy as np
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

from loguru import logger

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("ollama package not available - Ollama embeddings disabled")


class OllamaEmbeddingGenerator:
    """Generate embeddings using Ollama models."""
    
    def __init__(self, model_name: Optional[str] = None):
        from ..core.ai_config import model_for
        self.model_name = model_name or model_for("embedding")
        self.embedding_dim = None
        
        # Cache for embeddings
        self.cache_dir = Path("data/cache/ollama_embeddings")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        if OLLAMA_AVAILABLE:
            self._test_model()
        else:
            logger.error("ollama not installed. Install with: pip install ollama")
    
    def _test_model(self) -> bool:
        """Test if the model is available and working."""
        try:
            # Test embedding to get dimension
            logger.info(f"Testing Ollama embedding model: {self.model_name}")
            response = ollama.embeddings(
                model=self.model_name,
                prompt="test"
            )
            
            if 'embedding' in response:
                self.embedding_dim = len(response['embedding'])
                logger.info(f"Ollama model ready. Embedding dimension: {self.embedding_dim}")
                return True
            else:
                logger.error(f"Invalid response from Ollama model: {response}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to test Ollama embedding model: {e}")
            logger.info("Make sure Ollama is running and the model is downloaded:")
            logger.info(f"  ollama pull {self.model_name}")
            return False
    
    def is_available(self) -> bool:
        """Check if embeddings are available."""
        return OLLAMA_AVAILABLE and self.embedding_dim is not None
    
    def _prepare_text(self, text: str) -> str:
        """Prepare text for embedding generation."""
        if not text or not isinstance(text, str):
            return ""
        
        # Clean and limit text
        text = text.strip()
        
        # Limit to reasonable length (Ollama handles this well)
        if len(text) > 8000:
            text = text[:8000] + "..."
        
        return text
    
    def generate_embedding(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding for a single text."""
        if not self.is_available():
            return None
        
        text = self._prepare_text(text)
        if not text:
            return None
        
        try:
            response = ollama.embeddings(
                model=self.model_name,
                prompt=text
            )
            
            if 'embedding' in response:
                embedding = np.array(response['embedding'], dtype=np.float32)
                return embedding
            else:
                logger.debug(f"No embedding in response: {response}")
                return None
            
        except Exception as e:
            logger.debug(f"Error generating Ollama embedding: {e}")
            return None
    
    def generate_batch_embeddings(
        self, 
        texts: List[str],
        show_progress: bool = True
    ) -> List[Optional[np.ndarray]]:
        """Generate embeddings for multiple texts."""
        if not self.is_available():
            return [None] * len(texts)
        
        logger.info(f"Generating Ollama embeddings for {len(texts)} texts")
        
        embeddings = []
        
        for i, text in enumerate(texts):
            if show_progress and i % 10 == 0 and i > 0:
                logger.info(f"Processed {i}/{len(texts)} embeddings")
            
            embedding = self.generate_embedding(text)
            embeddings.append(embedding)
            
            # Small delay to avoid overwhelming Ollama
            time.sleep(0.1)
        
        logger.info(f"Generated {len([e for e in embeddings if e is not None])} valid embeddings")
        return embeddings
    
    def compute_similarity(
        self, 
        embedding1: np.ndarray, 
        embedding2: np.ndarray
    ) -> float:
        """Compute cosine similarity between two embeddings."""
        if embedding1 is None or embedding2 is None:
            return 0.0
        
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
    
    def find_similar_texts(
        self, 
        query_text: str, 
        text_embeddings: List[tuple], 
        limit: int = 10,
        min_similarity: float = 0.1
    ) -> List[tuple]:
        """Find texts similar to query."""
        if not self.is_available():
            return []
        
        query_embedding = self.generate_embedding(query_text)
        if query_embedding is None:
            return []
        
        similarities = []
        
        for text, embedding in text_embeddings:
            if embedding is not None:
                sim = self.compute_similarity(query_embedding, embedding)
                if sim >= min_similarity:
                    similarities.append((text, sim))
        
        # Sort by similarity and limit
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get embedding generator statistics."""
        return {
            "available": self.is_available(),
            "model": self.model_name,
            "embedding_dimension": self.embedding_dim,
            "cache_dir": str(self.cache_dir),
            "ollama_available": OLLAMA_AVAILABLE
        }