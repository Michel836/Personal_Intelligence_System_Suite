"""Enhanced content extractor with multiple format support and OCR."""

import time
import mimetypes
from pathlib import Path
from typing import Set, Optional, Dict, Any
import json
import re

from loguru import logger
from .base import BaseExtractor, ExtractionResult

# PDF Libraries
try:
    import PyPDF2
    from PyPDF2 import PdfReader
    import pdfplumber
    PDF_AVAILABLE = True
    PDF_ENHANCED = True
except ImportError:
    try:
        import PyPDF2
        from PyPDF2 import PdfReader
        PDF_AVAILABLE = True
        PDF_ENHANCED = False
    except ImportError:
        PDF_AVAILABLE = False
        PDF_ENHANCED = False

# Office Libraries
try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import openpyxl
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False

try:
    from pptx import Presentation
    POWERPOINT_AVAILABLE = True
except ImportError:
    POWERPOINT_AVAILABLE = False

# Additional Libraries
try:
    import eml_parser
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False

try:
    import markdown2
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False


class EnhancedExtractor(BaseExtractor):
    """Enhanced extractor supporting multiple formats with better text extraction."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {
            # Documents
            '.pdf', '.docx', '.doc', '.odt', '.rtf',
            # Spreadsheets  
            '.xlsx', '.xls', '.ods', '.csv',
            # Presentations
            '.pptx', '.ppt', '.odp',
            # Text formats
            '.txt', '.md', '.markdown', '.rst', '.log',
            # Code files
            '.py', '.js', '.html', '.htm', '.css', '.json', '.xml', '.yaml', '.yml',
            '.java', '.cpp', '.c', '.h', '.cs', '.php', '.rb', '.go', '.rs', '.ts',
            # Config files
            '.cfg', '.conf', '.ini', '.properties', '.env',
            # Email
            '.eml', '.msg',
            # Archives (metadata only)
            '.zip', '.rar', '.7z', '.tar', '.gz'
        }
        
        # Max file size for extraction (100MB)
        self.max_file_size = 100 * 1024 * 1024
        
        logger.info(f"EnhancedExtractor initialized with {len(self.supported_extensions)} supported extensions")
    
    def can_extract(self, file_path: Path) -> bool:
        """Check if file can be extracted."""
        if not file_path.exists():
            return False
        
        # Check extension
        if file_path.suffix.lower() not in self.supported_extensions:
            return False
        
        # Check file size
        try:
            if file_path.stat().st_size > self.max_file_size:
                logger.debug(f"File too large for extraction: {file_path}")
                return False
        except OSError:
            return False
        
        return True
    
    def extract_content(self, file_path: Path) -> ExtractionResult:
        """Extract content from file using appropriate method."""
        start_time = time.time()
        
        try:
            if not self.can_extract(file_path):
                return ExtractionResult(
                    success=False,
                    error="File cannot be extracted",
                    extraction_time=time.time() - start_time
                )
            
            extension = file_path.suffix.lower()
            
            # Route to appropriate extraction method
            if extension == '.pdf':
                result = self._extract_pdf(file_path)
            elif extension in ['.docx', '.doc']:
                result = self._extract_word(file_path)
            elif extension in ['.xlsx', '.xls', '.csv']:
                result = self._extract_excel(file_path)
            elif extension in ['.pptx', '.ppt']:
                result = self._extract_powerpoint(file_path)
            elif extension in ['.eml', '.msg']:
                result = self._extract_email(file_path)
            elif extension in ['.json', '.xml']:
                result = self._extract_structured(file_path)
            elif extension in ['.md', '.markdown']:
                result = self._extract_markdown(file_path)
            else:
                result = self._extract_text(file_path)
            
            result.extraction_time = time.time() - start_time
            return result
        
        except Exception as e:
            logger.error(f"Extraction error for {file_path}: {e}")
            return ExtractionResult(
                success=False,
                error=f"Extraction failed: {str(e)}",
                extraction_time=time.time() - start_time
            )
    
    def _extract_pdf(self, file_path: Path) -> ExtractionResult:
        """Extract text from PDF files."""
        text_content = []
        metadata = {}
        
        if not PDF_AVAILABLE:
            return ExtractionResult(success=False, error="PDF libraries not available")
        
        try:
            # Try pdfplumber first (better text extraction)
            if PDF_ENHANCED:
                try:
                    import pdfplumber
                    with pdfplumber.open(file_path) as pdf:
                        metadata['pages'] = len(pdf.pages)
                        metadata['pdf_metadata'] = pdf.metadata or {}
                        
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text_content.append(page_text)
                except Exception as e:
                    logger.debug(f"pdfplumber failed for {file_path}, trying PyPDF2: {e}")
                    raise e
            
            # Fallback to PyPDF2
            if not text_content:
                with open(file_path, 'rb') as file:
                    reader = PdfReader(file)
                    metadata['pages'] = len(reader.pages)
                    
                    if reader.metadata:
                        metadata['pdf_metadata'] = {
                            'title': reader.metadata.get('/Title', ''),
                            'author': reader.metadata.get('/Author', ''),
                            'subject': reader.metadata.get('/Subject', ''),
                            'creator': reader.metadata.get('/Creator', '')
                        }
                    
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text_content.append(page_text)
            
            content = '\n\n'.join(text_content).strip()
            
            if not content:
                return ExtractionResult(
                    success=False,
                    error="No text content found in PDF",
                    metadata=metadata
                )
            
            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"PDF extraction error: {str(e)}",
                metadata=metadata
            )
    
    def _extract_word(self, file_path: Path) -> ExtractionResult:
        """Extract text from Word documents."""
        if not DOCX_AVAILABLE:
            return ExtractionResult(success=False, error="python-docx not available")
        
        try:
            doc = DocxDocument(file_path)
            
            # Extract text from paragraphs
            text_content = []
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text_content.append(paragraph.text)
            
            # Extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        if cell.text.strip():
                            row_text.append(cell.text.strip())
                    if row_text:
                        text_content.append(' | '.join(row_text))
            
            content = '\n'.join(text_content).strip()
            
            # Metadata
            metadata = {
                'paragraphs': len(doc.paragraphs),
                'tables': len(doc.tables)
            }
            
            if hasattr(doc, 'core_properties') and doc.core_properties:
                cp = doc.core_properties
                metadata['word_metadata'] = {
                    'title': cp.title or '',
                    'author': cp.author or '',
                    'subject': cp.subject or '',
                    'created': str(cp.created) if cp.created else '',
                    'modified': str(cp.modified) if cp.modified else ''
                }
            
            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"Word extraction error: {str(e)}"
            )
    
    def _extract_excel(self, file_path: Path) -> ExtractionResult:
        """Extract text from Excel files."""
        if file_path.suffix.lower() == '.csv':
            return self._extract_csv(file_path)
        
        if not EXCEL_AVAILABLE:
            return ExtractionResult(success=False, error="openpyxl not available")
        
        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            
            text_content = []
            metadata = {
                'sheets': workbook.sheetnames,
                'total_sheets': len(workbook.sheetnames)
            }
            
            for sheet_name in workbook.sheetnames:
                worksheet = workbook[sheet_name]
                
                # Add sheet header
                text_content.append(f"=== Sheet: {sheet_name} ===")
                
                # Extract cell values
                for row in worksheet.iter_rows(values_only=True):
                    row_text = []
                    for cell_value in row:
                        if cell_value is not None:
                            row_text.append(str(cell_value))
                    
                    if row_text and any(cell.strip() for cell in row_text):
                        text_content.append(' | '.join(row_text))
            
            content = '\n'.join(text_content).strip()
            
            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"Excel extraction error: {str(e)}"
            )
    
    def _extract_csv(self, file_path: Path) -> ExtractionResult:
        """Extract text from CSV files."""
        try:
            import csv
            
            text_content = []
            
            with open(file_path, 'r', encoding='utf-8', newline='') as csvfile:
                # Try to detect delimiter
                sample = csvfile.read(1024)
                csvfile.seek(0)
                
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                
                reader = csv.reader(csvfile, delimiter=delimiter)
                
                for row_num, row in enumerate(reader):
                    if row and any(cell.strip() for cell in row):
                        text_content.append(' | '.join(str(cell) for cell in row))
                    
                    # Limit rows for very large CSVs
                    if row_num > 1000:
                        text_content.append("... [truncated: file too large] ...")
                        break
            
            content = '\n'.join(text_content).strip()
            metadata = {'format': 'CSV', 'delimiter': delimiter}
            
            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"CSV extraction error: {str(e)}"
            )
    
    def _extract_powerpoint(self, file_path: Path) -> ExtractionResult:
        """Extract text from PowerPoint files."""
        if not POWERPOINT_AVAILABLE:
            return ExtractionResult(success=False, error="python-pptx not available")
        
        try:
            presentation = Presentation(file_path)
            
            text_content = []
            metadata = {
                'slides': len(presentation.slides)
            }
            
            for slide_num, slide in enumerate(presentation.slides, 1):
                slide_text = [f"=== Slide {slide_num} ==="]
                
                # Extract text from shapes
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text.append(shape.text.strip())
                
                if len(slide_text) > 1:  # More than just the header
                    text_content.extend(slide_text)
            
            content = '\n'.join(text_content).strip()
            
            return ExtractionResult(
                success=True,
                content=content,
                metadata=metadata
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"PowerPoint extraction error: {str(e)}"
            )
    
    def _extract_email(self, file_path: Path) -> ExtractionResult:
        """Extract text from email files."""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Simple email parsing
            text_content = []
            headers = {}
            
            if file_path.suffix.lower() == '.eml':
                import email
                msg = email.message_from_bytes(content)
                
                # Extract headers
                headers = {
                    'from': msg.get('From', ''),
                    'to': msg.get('To', ''),
                    'subject': msg.get('Subject', ''),
                    'date': msg.get('Date', '')
                }
                
                # Extract body
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            text_content.append(part.get_payload(decode=True).decode('utf-8', errors='ignore'))
                else:
                    if msg.get_content_type() == "text/plain":
                        text_content.append(msg.get_payload(decode=True).decode('utf-8', errors='ignore'))
            
            content_text = '\n'.join(text_content).strip()
            
            # Add headers as readable text
            header_text = []
            for key, value in headers.items():
                if value:
                    header_text.append(f"{key.title()}: {value}")
            
            if header_text:
                content_text = '\n'.join(header_text) + '\n\n' + content_text
            
            return ExtractionResult(
                success=True,
                content=content_text,
                metadata={'email_headers': headers}
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"Email extraction error: {str(e)}"
            )
    
    def _extract_structured(self, file_path: Path) -> ExtractionResult:
        """Extract text from structured files (JSON, XML)."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            extension = file_path.suffix.lower()
            
            if extension == '.json':
                # Parse JSON and extract readable text
                try:
                    data = json.loads(content)
                    readable_text = self._json_to_text(data)
                    
                    return ExtractionResult(
                        success=True,
                        content=readable_text,
                        metadata={'format': 'JSON'}
                    )
                except json.JSONDecodeError:
                    # Fall back to raw content
                    pass
            
            elif extension == '.xml':
                # Basic XML text extraction
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(content)
                    text_content = []
                    
                    for elem in root.iter():
                        if elem.text and elem.text.strip():
                            text_content.append(elem.text.strip())
                    
                    readable_text = '\n'.join(text_content)
                    
                    return ExtractionResult(
                        success=True,
                        content=readable_text,
                        metadata={'format': 'XML'}
                    )
                except ET.ParseError:
                    # Fall back to raw content
                    pass
            
            # Fallback: return raw content
            return ExtractionResult(
                success=True,
                content=content,
                metadata={'format': extension.upper()}
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"Structured file extraction error: {str(e)}"
            )
    
    def _extract_markdown(self, file_path: Path) -> ExtractionResult:
        """Extract text from Markdown files."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Remove markdown formatting for better search
            cleaned_content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)  # Remove code blocks
            cleaned_content = re.sub(r'`[^`]+`', '', cleaned_content)  # Remove inline code
            cleaned_content = re.sub(r'#+\s*', '', cleaned_content)  # Remove headers
            cleaned_content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned_content)  # Convert links to text
            cleaned_content = re.sub(r'[*_]{1,2}([^*_]+)[*_]{1,2}', r'\1', cleaned_content)  # Remove emphasis
            
            return ExtractionResult(
                success=True,
                content=cleaned_content.strip(),
                metadata={'format': 'Markdown', 'original_length': len(content)}
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"Markdown extraction error: {str(e)}"
            )
    
    def _extract_text(self, file_path: Path) -> ExtractionResult:
        """Extract text from plain text files."""
        try:
            # Try different encodings
            encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    
                    return ExtractionResult(
                        success=True,
                        content=content,
                        metadata={'encoding': encoding, 'format': 'Text'}
                    )
                except UnicodeDecodeError:
                    continue
            
            return ExtractionResult(
                success=False,
                error="Could not decode file with any supported encoding"
            )
        
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"Text extraction error: {str(e)}"
            )
    
    def _json_to_text(self, obj, level: int = 0) -> str:
        """Convert JSON object to readable text."""
        lines = []
        indent = "  " * level
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"{indent}{key}:")
                    lines.append(self._json_to_text(value, level + 1))
                else:
                    lines.append(f"{indent}{key}: {value}")
        
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    lines.append(f"{indent}[{i}]:")
                    lines.append(self._json_to_text(item, level + 1))
                else:
                    lines.append(f"{indent}[{i}]: {item}")
        
        else:
            lines.append(f"{indent}{obj}")
        
        return '\n'.join(lines)
    
    def get_name(self) -> str:
        """Get extractor name."""
        return "EnhancedExtractor"