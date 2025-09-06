"""Test advanced search functionality."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.search.advanced_search import AdvancedSearch
from loguru import logger

def test_advanced_search():
    """Test advanced search with various combinations."""
    
    logger.info("🔍 Testing advanced search functionality...")
    
    search = AdvancedSearch()
    
    # Test 1: Simple text search
    try:
        logger.info("Test 1: Simple text search")
        result = search.search(
            query="ganneron vente banque",
            limit=5
        )
        
        if result['success']:
            logger.success(f"✅ Simple search: {len(result['results'])} results, total: {result['total_count']}")
        else:
            logger.error(f"❌ Simple search failed: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ Simple search exception: {e}")
    
    # Test 2: Search with file type filter
    try:
        logger.info("Test 2: Search with file type filter")
        result = search.search(
            query="pdf",
            file_types=["document"],
            limit=5
        )
        
        if result['success']:
            logger.success(f"✅ File type search: {len(result['results'])} results")
        else:
            logger.error(f"❌ File type search failed: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ File type search exception: {e}")
    
    # Test 3: Size filter only
    try:
        logger.info("Test 3: Size filter only")
        result = search.search(
            size_min=1000,
            size_max=100000,
            limit=5
        )
        
        if result['success']:
            logger.success(f"✅ Size filter: {len(result['results'])} results")
        else:
            logger.error(f"❌ Size filter failed: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ Size filter exception: {e}")
    
    # Test 4: Content filter
    try:
        logger.info("Test 4: Content filter")
        result = search.search(
            has_content=True,
            limit=5
        )
        
        if result['success']:
            logger.success(f"✅ Content filter: {len(result['results'])} results")
            for res in result['results'][:3]:
                if res.get('content_text'):
                    preview = res['content_text'][:50].replace('\n', ' ')
                    logger.info(f"  📄 {res['filename']}: {preview}...")
        else:
            logger.error(f"❌ Content filter failed: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ Content filter exception: {e}")
    
    # Test 5: Extension filter
    try:
        logger.info("Test 5: Extension filter")
        result = search.search(
            extensions=[".pdf", ".docx"],
            limit=5
        )
        
        if result['success']:
            logger.success(f"✅ Extension filter: {len(result['results'])} results")
        else:
            logger.error(f"❌ Extension filter failed: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ Extension filter exception: {e}")
    
    logger.info("🎉 Advanced search tests completed!")

if __name__ == "__main__":
    test_advanced_search()