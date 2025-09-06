"""Simple content extraction using direct libraries."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from loguru import logger
import sqlite3

# Direct extraction imports
try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

def extract_pdf_text(file_path):
    """Extract text from PDF using PyPDF2."""
    if not PDF_AVAILABLE:
        return None
    
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages[:5]:  # Only first 5 pages for speed
                text += page.extract_text() + "\n"
            return text.strip()
    except Exception as e:
        logger.debug(f"PDF extraction failed for {file_path}: {e}")
        return None

def extract_docx_text(file_path):
    """Extract text from DOCX using python-docx."""
    if not DOCX_AVAILABLE:
        return None
    
    try:
        doc = Document(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text.strip()
    except Exception as e:
        logger.debug(f"DOCX extraction failed for {file_path}: {e}")
        return None

def extract_text_file(file_path):
    """Extract text from plain text files."""
    try:
        # Try different encodings
        encodings = ['utf-8', 'windows-1252', 'iso-8859-1']
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as file:
                    return file.read()
            except UnicodeDecodeError:
                continue
        return None
    except Exception as e:
        logger.debug(f"Text extraction failed for {file_path}: {e}")
        return None

def simple_content_extraction():
    """Extract content from documents using simple methods."""
    
    logger.info("🚀 Starting simple content extraction...")
    
    db = DatabaseManager()
    
    # Query for smaller documents first
    conn = sqlite3.connect("data/indexes/files.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, path, filename, extension, size_bytes
        FROM files 
        WHERE extension IN ('.pdf', '.doc', '.docx', '.txt', '.rtf')
        AND size_bytes > 100  -- Skip tiny files
        AND size_bytes < 10000000  -- Skip files > 10MB for speed
        AND content_extracted = 0
        ORDER BY 
            CASE 
                WHEN extension = '.txt' THEN 1
                WHEN extension = '.docx' THEN 2
                WHEN extension = '.pdf' THEN 3
                ELSE 4
            END,
            size_bytes ASC
        LIMIT 20
    """)
    
    files_to_extract = cursor.fetchall()
    conn.close()
    
    logger.info(f"📋 Found {len(files_to_extract)} documents to extract")
    
    if not files_to_extract:
        logger.info("❌ No suitable documents found")
        return 0
    
    extracted_count = 0
    
    for file_id, file_path, filename, extension, size_bytes in files_to_extract:
        try:
            path = Path(file_path)
            if not path.exists():
                logger.warning(f"File not found: {file_path}")
                continue
            
            logger.info(f"📄 Extracting: {filename} ({size_bytes/1024:.1f}KB)")
            
            content = None
            
            # Choose extraction method based on extension
            if extension.lower() == '.pdf':
                content = extract_pdf_text(file_path)
            elif extension.lower() == '.docx':
                content = extract_docx_text(file_path)
            elif extension.lower() in ['.txt', '.rtf']:
                content = extract_text_file(file_path)
            
            if content and len(content.strip()) > 20:
                # Update database with content
                db.update_content(file_id, content)
                extracted_count += 1
                
                # Show preview
                preview = content[:200].replace('\n', ' ')
                logger.success(f"✅ Extracted {len(content)} chars: {preview}...")
                
                # Look for legal keywords
                text_lower = content.lower()
                legal_keywords = ['contrat', 'contract', 'agreement', 'loan', 'prêt', 'crédit', 'dupont', 'notaire', 'accord', 'vente', 'achat', 'propriété', 'immobilier']
                found_keywords = [kw for kw in legal_keywords if kw in text_lower]
                
                if found_keywords:
                    logger.info(f"🎯 LEGAL KEYWORDS FOUND: {', '.join(found_keywords)}")
            else:
                logger.warning(f"❌ No content extracted from {filename}")
                
        except Exception as e:
            logger.error(f"Failed to extract {filename}: {e}")
    
    logger.success(f"🎉 Simple extraction complete! Processed {extracted_count}/{len(files_to_extract)} documents")
    
    if extracted_count > 0:
        logger.info("🔍 Now you can search in content using the web interface!")
        logger.info("Try searching for: 'contrat', 'agreement', 'loan', or specific names")
    
    return extracted_count

if __name__ == "__main__":
    simple_content_extraction()