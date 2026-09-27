"""Plain text file extractor."""

import time
from pathlib import Path

from loguru import logger
from .base import BaseExtractor, ExtractionResult


class TextExtractor(BaseExtractor):
    """Extract content from plain text files."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {
            '.txt', '.log', '.md', '.csv', 
            '.json', '.xml', '.html', '.htm',
            '.py', '.js', '.css', '.sql',
            '.yaml', '.yml', '.ini', '.cfg',
            '.bat', '.sh', '.ps1', '.msg'
        }
        
        # Encodings to try in order
        self.encodings = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252', 'ascii']
        
        # Max file size to process (50MB)
        self.max_size = 50 * 1024 * 1024
    
    def can_extract(self, file_path: Path) -> bool:
        """Check if file is a supported text file."""
        return (
            file_path.suffix.lower() in self.supported_extensions and
            file_path.is_file()
        )
    
    def extract_content(self, file_path: Path) -> ExtractionResult:
        """Extract content from text file."""
        start_time = time.time()
        
        try:
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > self.max_size:
                return ExtractionResult(
                    success=False,
                    error=f"File too large: {file_size / (1024*1024):.1f}MB (max {self.max_size / (1024*1024)}MB)",
                    extraction_time=time.time() - start_time
                )
            
            # Try different encodings
            content = None
            encoding_used = None
            
            for encoding in self.encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    encoding_used = encoding
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.debug(f"Error reading {file_path} with {encoding}: {e}")
                    continue
            
            if content is None:
                return ExtractionResult(
                    success=False,
                    error="Could not decode file with any supported encoding",
                    extraction_time=time.time() - start_time
                )
            
            # Basic content analysis
            lines = content.split('\n')
            words = content.split()
            
            metadata = {
                'encoding': encoding_used,
                'file_size_bytes': file_size,
                'lines': len(lines),
                'characters': len(content),
                'words': len(words),
                'extension': file_path.suffix.lower()
            }
            
            # Add specific metadata based on file type
            extension = file_path.suffix.lower()
            if extension == '.csv':
                metadata['estimated_rows'] = max(0, len(lines) - 1)  # Assuming header
                metadata['estimated_columns'] = len(lines[0].split(',')) if lines else 0
            elif extension in ['.json', '.xml', '.html']:
                metadata['structured_data'] = True
            elif extension in ['.py', '.js', '.css', '.sql']:
                metadata['code_file'] = True
                # Count rough code metrics
                non_empty_lines = [line for line in lines if line.strip()]
                metadata['code_lines'] = len(non_empty_lines)
            
            return ExtractionResult(
                success=True,
                content=content,
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
            logger.debug(f"Error extracting text from {file_path}: {e}")
            return ExtractionResult(
                success=False,
                error=f"Text extraction error: {str(e)}",
                extraction_time=time.time() - start_time
            )