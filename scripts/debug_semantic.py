"""Debug semantic search issues."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.intelligence.embeddings import EmbeddingGenerator  
from src.intelligence.semantic_search import SemanticSearchEngine
from src.core.database import DatabaseManager

def debug_semantic():
    """Debug semantic search step by step."""
    
    print("🔍 Debugging Semantic Search")
    print("=" * 40)
    
    # Test 1: Embedding Generator
    print("1. Testing Embedding Generator...")
    embedding_gen = EmbeddingGenerator()
    
    print(f"   Available: {embedding_gen.is_available()}")
    print(f"   Model: {embedding_gen.model_name}")
    print(f"   Dimension: {embedding_gen.embedding_dim}")
    
    if not embedding_gen.is_available():
        print("❌ Embedding generator not available!")
        print("Install: pip install sentence-transformers")
        return
    
    # Test 2: Generate test embedding
    print("\n2. Testing embedding generation...")
    test_text = "python programming language"
    embedding = embedding_gen.generate_embedding(test_text)
    
    if embedding is not None:
        print(f"   ✅ Generated embedding: shape {embedding.shape}")
    else:
        print("   ❌ Failed to generate embedding")
        return
    
    # Test 3: Database content
    print("\n3. Checking database content...")
    db = DatabaseManager()
    
    with db.get_connection() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) FROM files 
            WHERE content_extracted = 1 
            AND content_text IS NOT NULL
            AND length(content_text) > 50
        """)
        count = cursor.fetchone()[0]
        print(f"   📄 Documents with content: {count}")
        
        if count == 0:
            print("   ❌ No documents with extracted content!")
            print("   Run: python scripts/extract_content.py 100")
            return
        
        # Get a sample document
        cursor = conn.execute("""
            SELECT id, filename, content_text FROM files 
            WHERE content_extracted = 1 
            AND content_text IS NOT NULL
            AND length(content_text) > 50
            LIMIT 3
        """)
        
        docs = cursor.fetchall()
        print(f"   📄 Sample documents:")
        for doc in docs:
            print(f"      - {doc[1]} (content: {len(doc[2])} chars)")
    
    # Test 4: Semantic search engine  
    print("\n4. Testing semantic search engine...")
    semantic_engine = SemanticSearchEngine(db)
    
    print(f"   Available: {semantic_engine.is_available()}")
    stats = semantic_engine.get_stats()
    print(f"   Documents with content: {stats['documents_with_content']}")
    print(f"   Cached embeddings: {stats['cached_embeddings']}")
    
    # Test 5: Manual search
    print("\n5. Testing manual semantic search...")
    try:
        results = semantic_engine.semantic_search(
            "python",
            limit=5,
            similarity_threshold=0.1
        )
        print(f"   🎯 Found {len(results)} results with threshold 0.1")
        
        for i, result in enumerate(results[:3]):
            print(f"      {i+1}. {result['filename']} (similarity: {result.get('semantic_similarity', 'N/A')})")
    
    except Exception as e:
        print(f"   ❌ Search failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 6: Try different queries
    test_queries = ["test", "file", "import", "error"]
    
    print("\n6. Testing various queries...")
    for query in test_queries:
        try:
            results = semantic_engine.semantic_search(
                query,
                limit=3, 
                similarity_threshold=0.1
            )
            print(f"   '{query}': {len(results)} results")
        except Exception as e:
            print(f"   '{query}': ERROR - {e}")
    
    print("\n✅ Debug complete!")

if __name__ == "__main__":
    debug_semantic()