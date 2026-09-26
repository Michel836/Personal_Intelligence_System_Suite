"""Extraction manager to coordinate all extractors."""

import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger
from .base import BaseExtractor, ExtractionResult
from .pdf_extractor import PDFExtractor
from .office_extractor import OfficeExtractor
from .odf_extractor import OdfExtractor
from .text_extractor import TextExtractor


class ExtractionManager:
    """Manages content extraction from multiple file types."""
    
    def __init__(self, max_workers: int = 2):
        self.extractors: List[BaseExtractor] = [
            PDFExtractor(),
            OfficeExtractor(),
            OdfExtractor(),
            TextExtractor(),
        ]
        self.max_workers = max_workers
        
        # Statistics
        self.stats = {
            'total_processed': 0,
            'successful_extractions': 0,
            'failed_extractions': 0,
            'total_extraction_time': 0.0,
            'by_extractor': {}
        }
        
        logger.info(f"ExtractionManager initialized with {len(self.extractors)} extractors")
    
    def get_extractor_for_file(self, file_path: Path) -> Optional[BaseExtractor]:
        """Find the appropriate extractor for a file."""
        for extractor in self.extractors:
            if extractor.can_extract(file_path):
                return extractor
        return None
    
    @staticmethod
    def _try_ocr(file_path: Path, start_time: float) -> Optional[ExtractionResult]:
        """Optional Tesseract fallback (disabled unless PIS_OCR_ENABLED=1)."""
        try:
            from .ocr import IMAGE_EXTENSIONS, PDF_EXTENSIONS, ocr_enabled, ocr_file
        except Exception:
            return None
        if not ocr_enabled() or file_path.suffix.lower() not in (IMAGE_EXTENSIONS | PDF_EXTENSIONS):
            return None
        return ocr_file(file_path)

    def extract_single(self, file_path: Path) -> ExtractionResult:
        """Extract content from a single file (with optional OCR fallback)."""
        start_time = time.time()

        # Find appropriate extractor
        extractor = self.get_extractor_for_file(file_path)
        if not extractor:
            ocr_result = self._try_ocr(file_path, start_time)
            if ocr_result is not None:
                self._update_stats("ocr", ocr_result)
                return ocr_result
            return ExtractionResult(
                success=False,
                error="No suitable extractor found",
                extraction_time=time.time() - start_time
            )

        # Perform extraction; fall back to OCR when no text was produced.
        try:
            result = extractor.extract_content(file_path)
            if not result.success or not (result.content or "").strip():
                ocr_result = self._try_ocr(file_path, start_time)
                if ocr_result is not None and ocr_result.success:
                    result = ocr_result

            # Update statistics
            self._update_stats(extractor.get_name(), result)
            
            return result
        
        except Exception as e:
            logger.error(f"Extraction failed for {file_path}: {e}")
            result = ExtractionResult(
                success=False,
                error=f"Extractor error: {str(e)}",
                extraction_time=time.time() - start_time
            )
            
            self._update_stats(extractor.get_name(), result)
            return result
    
    def extract_batch(
        self, 
        file_paths: List[Path],
        progress_callback: Optional[callable] = None
    ) -> Dict[str, ExtractionResult]:
        """Extract content from multiple files in parallel."""
        
        results = {}
        total_files = len(file_paths)
        processed = 0
        
        logger.info(f"Starting batch extraction of {total_files} files")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all extraction tasks
            future_to_path = {
                executor.submit(self.extract_single, path): path 
                for path in file_paths
            }
            
            # Process completed tasks
            for future in as_completed(future_to_path):
                file_path = future_to_path[future]
                
                try:
                    result = future.result()
                    results[str(file_path)] = result
                    processed += 1
                    
                    # Progress callback
                    if progress_callback and processed % 10 == 0:
                        progress_callback(processed, total_files)
                    
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    results[str(file_path)] = ExtractionResult(
                        success=False,
                        error=f"Processing error: {str(e)}"
                    )
                    processed += 1
        
        logger.info(f"Batch extraction completed: {processed} files processed")
        return results
    
    def extract_priority_files(
        self, 
        file_paths: List[Path],
        limit: int = 100
    ) -> Dict[str, ExtractionResult]:
        """Extract content from high-priority files first."""
        
        # Sort by priority (PDFs and Office docs first, then by size)
        def get_priority(path: Path) -> tuple:
            ext = path.suffix.lower()
            
            # Priority levels (lower = higher priority)
            if ext == '.pdf':
                priority = 1
            elif ext in ['.docx', '.xlsx', '.pptx']:
                priority = 2
            elif ext in ['.doc', '.xls', '.ppt']:
                priority = 3
            elif ext in ['.txt', '.log', '.md']:
                priority = 4
            else:
                priority = 5
            
            # Secondary sort by size (smaller first for speed)
            try:
                size = path.stat().st_size
            except:
                size = float('inf')
            
            return (priority, size)
        
        # Sort and limit
        sorted_files = sorted(file_paths, key=get_priority)[:limit]
        
        logger.info(f"Extracting {len(sorted_files)} priority files")
        return self.extract_batch(sorted_files)
    
    def can_extract_file(self, file_path: Path) -> bool:
        """Check if any extractor can handle this file."""
        return self.get_extractor_for_file(file_path) is not None
    
    def get_supported_extensions(self) -> set:
        """Get all supported file extensions."""
        extensions = set()
        for extractor in self.extractors:
            extensions.update(extractor.supported_extensions)
        return extensions
    
    def get_stats(self) -> Dict[str, Any]:
        """Get extraction statistics."""
        stats = self.stats.copy()
        
        # Add derived metrics
        if stats['total_processed'] > 0:
            stats['success_rate'] = (
                stats['successful_extractions'] / stats['total_processed'] * 100
            )
            stats['avg_extraction_time'] = (
                stats['total_extraction_time'] / stats['total_processed']
            )
        else:
            stats['success_rate'] = 0.0
            stats['avg_extraction_time'] = 0.0
        
        return stats
    
    def reset_stats(self) -> None:
        """Reset extraction statistics."""
        self.stats = {
            'total_processed': 0,
            'successful_extractions': 0,
            'failed_extractions': 0,
            'total_extraction_time': 0.0,
            'by_extractor': {}
        }
        logger.info("Extraction statistics reset")
    
    def _update_stats(self, extractor_name: str, result: ExtractionResult) -> None:
        """Update internal statistics."""
        self.stats['total_processed'] += 1
        self.stats['total_extraction_time'] += result.extraction_time
        
        if result.success:
            self.stats['successful_extractions'] += 1
        else:
            self.stats['failed_extractions'] += 1
        
        # Per-extractor stats
        if extractor_name not in self.stats['by_extractor']:
            self.stats['by_extractor'][extractor_name] = {
                'processed': 0,
                'successful': 0,
                'failed': 0,
                'total_time': 0.0
            }
        
        extractor_stats = self.stats['by_extractor'][extractor_name]
        extractor_stats['processed'] += 1
        extractor_stats['total_time'] += result.extraction_time
        
        if result.success:
            extractor_stats['successful'] += 1
        else:
            extractor_stats['failed'] += 1