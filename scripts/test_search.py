"""Test search functionality."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from loguru import logger

def test_search():
    """Test database search functionality."""
    
    logger.info("🔍 Testing search functionality...")
    
    db = DatabaseManager()
    
    # Test 1: Basic search
    try:
        logger.info("Test 1: Basic search with no filters")
        results = db.search_files(limit=5)
        logger.success(f"✅ Basic search: {len(results)} results")
        
        if results:
            for i, result in enumerate(results[:2]):
                logger.info(f"  {i+1}. {result['filename']} ({result['size_bytes']} bytes)")
    except Exception as e:
        logger.error(f"❌ Basic search failed: {e}")
    
    # Test 2: Text search
    try:
        logger.info("Test 2: Text search for 'pdf'")
        results = db.search_files(query="pdf", limit=5)
        logger.success(f"✅ Text search: {len(results)} results")
    except Exception as e:
        logger.error(f"❌ Text search failed: {e}")
    
    # Test 3: Extension filter
    try:
        logger.info("Test 3: Extension filter for .pdf")
        results = db.search_files(extension=".pdf", limit=5)
        logger.success(f"✅ Extension filter: {len(results)} results")
    except Exception as e:
        logger.error(f"❌ Extension filter failed: {e}")
    
    # Test 4: Size filter
    try:
        logger.info("Test 4: Size filter (>1MB)")
        results = db.search_files(min_size=1024*1024, limit=5)
        logger.success(f"✅ Size filter: {len(results)} results")
    except Exception as e:
        logger.error(f"❌ Size filter failed: {e}")
    
    # Test 5: Combined search
    try:
        logger.info("Test 5: Combined search (text + size)")
        results = db.search_files(query="data", min_size=1000, limit=5)
        logger.success(f"✅ Combined search: {len(results)} results")
    except Exception as e:
        logger.error(f"❌ Combined search failed: {e}")
    
    # Test 6: Content search (should work now with extracted content)
    try:
        logger.info("Test 6: Content search for 'download'")
        results = db.search_files(query="download", limit=5)
        logger.success(f"✅ Content search: {len(results)} results")
        
        for result in results:
            if result.get('content_text'):
                preview = result['content_text'][:100].replace('\n', ' ')
                logger.info(f"  📄 {result['filename']}: {preview}...")
                
    except Exception as e:
        logger.error(f"❌ Content search failed: {e}")
    
    logger.info("🎉 Search tests completed!")

if __name__ == "__main__":
    test_search()