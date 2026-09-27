"""PDF content extractor."""

import time
from pathlib import Path

from loguru import logger
from .base import BaseExtractor, ExtractionResult

try:
    import PyPDF2
    from PyPDF2 import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("PyPDF2 not available - PDF extraction disabled")


class PDFExtractor(BaseExtractor):
    """Extract text content from PDF files."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {'.pdf'}
    
    def can_extract(self, file_path: Path) -> bool:
        """Check if file is a PDF."""
        return (
            PDF_AVAILABLE and 
            file_path.suffix.lower() in self.supported_extensions and
            file_path.is_file()
        )
    
    def extract_content(self, file_path: Path) -> ExtractionResult:
        """Extract text from PDF file."""
        if not PDF_AVAILABLE:
            return ExtractionResult(
                success=False,
                error="PyPDF2 not available"
            )
        
        start_time = time.time()
        
        try:
            with open(file_path, 'rb') as file:
                reader = PdfReader(file)
                
                # Extract metadata
                metadata = {
                    'pages': len(reader.pages),
                    'encrypted': reader.is_encrypted
                }
                
                # Handle encrypted PDFs
                if reader.is_encrypted:
                    logger.debug(f"PDF is encrypted: {file_path}")
                    return ExtractionResult(
                        success=False,
                        error="PDF is encrypted",
                        metadata=metadata,
                        extraction_time=time.time() - start_time
                    )
                
                # Extract text from all pages
                text_content = []
                pages_processed = 0
                
                for page_num, page in enumerate(reader.pages):
                    try:
                        text = page.extract_text()
                        if text.strip():
                            text_content.append(text)
                        pages_processed += 1
                        
                        # Limit processing for very large PDFs
                        if pages_processed > 100:
                            logger.debug(f"Stopped at page {page_num} for large PDF: {file_path}")
                            break
                            
                    except Exception as e:
                        logger.debug(f"Error extracting page {page_num} from {file_path}: {e}")
                        continue
                
                # Combine all text
                full_text = '\n'.join(text_content)
                
                # Add extraction metadata
                metadata.update({
                    'pages_processed': pages_processed,
                    'characters': len(full_text),
                    'words': len(full_text.split()) if full_text else 0
                })
                
                # Get additional PDF metadata if available
                if reader.metadata:
                    try:
                        pdf_info = reader.metadata
                        metadata.update({
                            'title': str(pdf_info.get('/Title', '')),
                            'author': str(pdf_info.get('/Author', '')),
                            'subject': str(pdf_info.get('/Subject', '')),
                            'creator': str(pdf_info.get('/Creator', '')),
                            'producer': str(pdf_info.get('/Producer', '')),
                            'creation_date': str(pdf_info.get('/CreationDate', '')),
                            'modification_date': str(pdf_info.get('/ModDate', ''))
                        })
                    except Exception as e:
                        logger.debug(f"Error extracting PDF metadata from {file_path}: {e}")
                
                return ExtractionResult(
                    success=True,
                    content=full_text,
                    metadata=metadata,
                    extraction_time=time.time() - start_time
                )
        
        except FileNotFoundError:
            return ExtractionResult(
                success=False,
                error="File not found",
                extraction_time=time.time() - start_time
            )
        except PermissionError:
            return ExtractionResult(
                success=False,
                error="Permission denied",
                extraction_time=time.time() - start_time
            )
        except Exception as e:
            logger.debug(f"Error extracting PDF {file_path}: {e}")
            return ExtractionResult(
                success=False,
                error=f"PDF extraction error: {str(e)}",
                extraction_time=time.time() - start_time
            )