"""Quick script to activate content extraction for legal documents."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from src.extractors.auto_extractor import AutoExtractor
from loguru import logger

def activate_extraction():
    """Start extracting content from PDFs and documents."""
    
    logger.info("🚀 Starting content extraction for legal documents...")
    
    db = DatabaseManager()
    extractor = AutoExtractor()
    
    # Get priority documents (PDFs, DOCX, etc.)
    logger.info("📋 Finding priority documents to extract...")
    
    # Focus on legal document extensions
    legal_extensions = ['.pdf', '.doc', '.docx', '.rtf', '.txt', '.msg', '.eml']
    
    results = db.search_files(
        query=None,
        file_type=None,
        priority=None,
        extension=None,
        limit=100  # Start with 100 files
    )
    
    logger.info(f"Found {len(results)} documents to process")
    
    extracted_count = 0
    for file_data in results:
        try:
            file_path = Path(file_data['path'])
            if file_path.exists() and file_path.suffix.lower() in legal_extensions:
                logger.info(f"Extracting: {file_path.name}")
                
                # Extract content
                content = extractor.extract(str(file_path))
                
                if content and content.get('text'):
                    # Update database with content
                    db.update_content(file_data['id'], content['text'])
                    extracted_count += 1
                    logger.success(f"✅ Extracted: {file_path.name}")
                    
                    # Show preview of content
                    preview = content['text'][:200] if len(content['text']) > 200 else content['text']
                    logger.debug(f"Preview: {preview}...")
                    
        except Exception as e:
            logger.error(f"Failed to extract {file_data['path']}: {e}")
    
    logger.success(f"🎉 Extraction complete! Processed {extracted_count} documents")
    
    # Show statistics
    stats = db.get_statistics()
    logger.info(f"📊 Total files: {stats['total_files']:,}")
    logger.info(f"📄 Documents with content: {extracted_count}")
    
    return extracted_count

if __name__ == "__main__":
    activate_extraction()