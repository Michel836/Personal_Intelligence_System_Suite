"""Automatic content extraction system for batch processing."""

import time
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from loguru import logger
from .manager import ExtractionManager
from .enhanced_extractor import EnhancedExtractor


class AutoExtractor:
    """Automatic content extraction system for large-scale processing."""
    
    def __init__(self, db_path=None, max_workers: int = 4):
        from ..core.database import default_db_path
        self.db_path = db_path or default_db_path()
        self.max_workers = max_workers
        
        # Initialize extraction manager with enhanced extractor
        self.extraction_manager = ExtractionManager(max_workers=max_workers)
        
        # Add our enhanced extractor
        enhanced_extractor = EnhancedExtractor()
        self.extraction_manager.extractors.insert(0, enhanced_extractor)
        
        # Statistics
        self.stats = {
            'total_candidates': 0,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'start_time': None,
            'end_time': None
        }
        
        self.is_running = False
        self.stop_requested = False
        
        logger.info(f"AutoExtractor initialized with {len(self.extraction_manager.extractors)} extractors")
    
    def get_extraction_candidates(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get files that need content extraction."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Find files without extracted content
            query = """
                SELECT id, path, filename, file_type, size_bytes
                FROM files 
                WHERE (content_text IS NULL OR content_text = '')
                AND content_extracted = 0
                ORDER BY 
                    CASE file_type
                        WHEN 'document' THEN 1
                        WHEN 'text' THEN 2  
                        ELSE 3
                    END,
                    size_bytes ASC
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query)
            
            candidates = []
            for row in cursor.fetchall():
                candidates.append({
                    'id': row[0],
                    'path': row[1],
                    'filename': row[2],
                    'file_type': row[3],
                    'size_bytes': row[4] or 0
                })
            
            conn.close()
            
            # Filter existing files
            valid_candidates = []
            for candidate in candidates:
                file_path = Path(candidate['path'])
                if file_path.exists() and self.extraction_manager.can_extract_file(file_path):
                    valid_candidates.append(candidate)
            
            logger.info(f"Found {len(valid_candidates)} files ready for extraction")
            return valid_candidates
        
        except Exception as e:
            logger.error(f"Error getting extraction candidates: {e}")
            return []
    
    def extract_priority_batch(self, batch_size: int = 100, progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Extract content from a priority batch of files."""
        candidates = self.get_extraction_candidates(batch_size)
        
        if not candidates:
            logger.info("No files found for extraction")
            return {'processed': 0, 'successful': 0, 'failed': 0}
        
        self.stats['total_candidates'] = len(candidates)
        self.stats['start_time'] = datetime.now()
        self.is_running = True
        
        results = {'processed': 0, 'successful': 0, 'failed': 0, 'details': []}
        
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit extraction tasks
                future_to_candidate = {}
                for candidate in candidates:
                    if self.stop_requested:
                        break
                    
                    file_path = Path(candidate['path'])
                    future = executor.submit(self._extract_and_save, candidate)
                    future_to_candidate[future] = candidate
                
                # Process completed tasks
                for future in as_completed(future_to_candidate):
                    if self.stop_requested:
                        break
                    
                    candidate = future_to_candidate[future]
                    
                    try:
                        extraction_result = future.result()
                        results['processed'] += 1
                        
                        if extraction_result['success']:
                            results['successful'] += 1
                            self.stats['successful'] += 1
                        else:
                            results['failed'] += 1
                            self.stats['failed'] += 1
                        
                        results['details'].append({
                            'filename': candidate['filename'],
                            'success': extraction_result['success'],
                            'content_length': extraction_result.get('content_length', 0),
                            'error': extraction_result.get('error', ''),
                            'extraction_time': extraction_result.get('extraction_time', 0)
                        })
                        
                        # Progress callback
                        if progress_callback and results['processed'] % 10 == 0:
                            progress_callback(results['processed'], len(candidates), results)
                    
                    except Exception as e:
                        logger.error(f"Error processing {candidate['filename']}: {e}")
                        results['failed'] += 1
                        self.stats['failed'] += 1
        
        finally:
            self.is_running = False
            self.stats['end_time'] = datetime.now()
            self.stats['processed'] = results['processed']
        
        logger.info(f"Batch extraction completed: {results['successful']}/{results['processed']} successful")
        return results
    
    def extract_all_candidates(self, progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Extract content from all available candidates."""
        all_candidates = self.get_extraction_candidates()
        
        if not all_candidates:
            logger.info("No files found for extraction")
            return {'processed': 0, 'successful': 0, 'failed': 0}
        
        logger.info(f"Starting extraction of {len(all_candidates)} files")
        
        # Process in batches to avoid memory issues
        batch_size = 500
        total_results = {'processed': 0, 'successful': 0, 'failed': 0, 'batches': []}
        
        for i in range(0, len(all_candidates), batch_size):
            if self.stop_requested:
                break
            
            batch = all_candidates[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(all_candidates) + batch_size - 1)//batch_size}")
            
            # Update candidates to current batch
            self.stats['total_candidates'] = len(batch)
            batch_results = self._process_batch(batch, progress_callback)
            
            total_results['processed'] += batch_results['processed']
            total_results['successful'] += batch_results['successful']
            total_results['failed'] += batch_results['failed']
            total_results['batches'].append(batch_results)
            
            # Short break between batches
            time.sleep(1)
        
        logger.info(f"All batches completed: {total_results['successful']}/{total_results['processed']} successful")
        return total_results
    
    def _process_batch(self, candidates: List[Dict[str, Any]], progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Process a single batch of candidates."""
        results = {'processed': 0, 'successful': 0, 'failed': 0, 'details': []}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_candidate = {}
            
            for candidate in candidates:
                if self.stop_requested:
                    break
                
                future = executor.submit(self._extract_and_save, candidate)
                future_to_candidate[future] = candidate
            
            for future in as_completed(future_to_candidate):
                if self.stop_requested:
                    break
                
                candidate = future_to_candidate[future]
                
                try:
                    extraction_result = future.result()
                    results['processed'] += 1
                    
                    if extraction_result['success']:
                        results['successful'] += 1
                    else:
                        results['failed'] += 1
                    
                    if progress_callback and results['processed'] % 25 == 0:
                        progress_callback(results['processed'], len(candidates), results)
                
                except Exception as e:
                    logger.error(f"Batch processing error for {candidate['filename']}: {e}")
                    results['failed'] += 1
        
        return results
    
    def _extract_and_save(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Extract content from a file and save to database."""
        file_path = Path(candidate['path'])
        
        try:
            # Perform extraction
            extraction_result = self.extraction_manager.extract_single(file_path)
            
            # Save to database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if extraction_result.success and extraction_result.content:
                # Update with extracted content
                cursor.execute("""
                    UPDATE files 
                    SET content_text = ?, content_extracted = 1, indexed_at = ?
                    WHERE id = ?
                """, (extraction_result.content, datetime.now().isoformat(), candidate['id']))
                
                logger.debug(f"Extracted {len(extraction_result.content)} chars from {candidate['filename']}")
            else:
                # Mark as attempted but failed
                cursor.execute("""
                    UPDATE files 
                    SET content_extracted = 1, indexed_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), candidate['id']))
                
                logger.debug(f"Failed to extract content from {candidate['filename']}: {extraction_result.error}")
            
            conn.commit()
            conn.close()
            
            return {
                'success': extraction_result.success,
                'content_length': len(extraction_result.content) if extraction_result.content else 0,
                'error': extraction_result.error,
                'extraction_time': extraction_result.extraction_time
            }
        
        except Exception as e:
            logger.error(f"Error in _extract_and_save for {candidate['filename']}: {e}")
            return {
                'success': False,
                'content_length': 0,
                'error': str(e),
                'extraction_time': 0
            }
    
    def get_extraction_stats(self) -> Dict[str, Any]:
        """Get current extraction statistics."""
        stats = self.stats.copy()
        
        if stats['start_time'] and stats['end_time']:
            duration = stats['end_time'] - stats['start_time']
            stats['duration_seconds'] = duration.total_seconds()
            
            if stats['processed'] > 0:
                stats['files_per_second'] = stats['processed'] / duration.total_seconds()
        
        # Add extraction manager stats
        manager_stats = self.extraction_manager.get_stats()
        stats['extraction_manager'] = manager_stats
        
        return stats
    
    def stop_extraction(self):
        """Request to stop the extraction process."""
        self.stop_requested = True
        logger.info("Extraction stop requested")
    
    def reset_stats(self):
        """Reset extraction statistics."""
        self.stats = {
            'total_candidates': 0,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'start_time': None,
            'end_time': None
        }
        self.extraction_manager.reset_stats()
    
    def estimate_extraction_time(self, file_count: int = None) -> Dict[str, Any]:
        """Estimate time required for extraction."""
        if file_count is None:
            candidates = self.get_extraction_candidates()
            file_count = len(candidates)
        
        # Base estimates per file type (seconds)
        estimates = {
            'small_text': 0.1,      # < 100KB text files
            'large_text': 0.5,      # > 100KB text files  
            'pdf': 2.0,             # PDF files
            'office': 1.5,          # Word/Excel/PowerPoint
            'other': 0.3            # Other formats
        }
        
        # Simple estimation (can be improved with historical data)
        avg_time_per_file = 0.8  # seconds
        total_time = file_count * avg_time_per_file / self.max_workers
        
        return {
            'file_count': file_count,
            'estimated_seconds': total_time,
            'estimated_minutes': total_time / 60,
            'max_workers': self.max_workers,
            'note': 'Estimate based on average processing time'
        }