"""Extract content from legal documents specifically."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from src.extractors.auto_extractor import AutoExtractor
from loguru import logger
import sqlite3

def find_and_extract_legal_documents():
    """Find and extract legal documents prioritizing PDFs and Word docs."""
    
    logger.info("🔍 Searching for legal documents...")
    
    db = DatabaseManager()
    extractor = AutoExtractor()
    
    # Query directly for documents with legal extensions
    conn = sqlite3.connect("data/indexes/files.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, path, filename, extension, size_bytes
        FROM files 
        WHERE extension IN ('.pdf', '.doc', '.docx', '.rtf', '.txt', '.msg', '.eml')
        AND size_bytes > 1024  -- Skip tiny files
        AND size_bytes < 50000000  -- Skip huge files (>50MB)
        AND content_extracted = 0
        ORDER BY 
            CASE 
                WHEN extension IN ('.pdf', '.doc', '.docx') THEN 1
                WHEN extension IN ('.msg', '.eml') THEN 2
                ELSE 3
            END,
            size_bytes DESC
        LIMIT 50
    """)
    
    files_to_extract = cursor.fetchall()
    conn.close()
    
    logger.info(f"📋 Found {len(files_to_extract)} legal documents to extract")
    
    if not files_to_extract:
        logger.info("❌ No legal documents found to extract")
        return 0
    
    extracted_count = 0
    
    for file_id, file_path, filename, extension, size_bytes in files_to_extract:
        try:
            path = Path(file_path)
            if not path.exists():
                logger.warning(f"File not found: {file_path}")
                continue
            
            logger.info(f"📄 Extracting: {filename} ({size_bytes/1024/1024:.1f}MB)")
            
            # Extract content
            content = extractor.extract(str(path))
            
            if content and content.get('text') and len(content['text'].strip()) > 50:
                # Update database with content
                db.update_content(file_id, content['text'])
                extracted_count += 1
                
                # Show preview
                preview = content['text'][:300].replace('\n', ' ')
                logger.success(f"✅ Extracted {len(content['text'])} chars: {preview}...")
                
                # Look for legal keywords
                text_lower = content['text'].lower()
                legal_keywords = ['contrat', 'contract', 'agreement', 'loan', 'prêt', 'crédit', 'dupont', 'notaire', 'accord']
                found_keywords = [kw for kw in legal_keywords if kw in text_lower]
                
                if found_keywords:
                    logger.info(f"🎯 LEGAL KEYWORDS FOUND: {', '.join(found_keywords)}")
            else:
                logger.warning(f"❌ No content extracted from {filename}")
                
        except Exception as e:
            logger.error(f"Failed to extract {filename}: {e}")
    
    logger.success(f"🎉 Extraction complete! Processed {extracted_count}/{len(files_to_extract)} documents")
    
    # Update statistics
    stats = db.get_statistics()
    logger.info(f"📊 Total files in database: {stats['total_files']:,}")
    logger.info(f"📄 Documents with content: {extracted_count}")
    
    return extracted_count

if __name__ == "__main__":
    find_and_extract_legal_documents()