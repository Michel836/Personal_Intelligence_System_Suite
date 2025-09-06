"""Advanced search system with multiple filters and options."""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import re

from loguru import logger


class AdvancedSearch:
    """Advanced search system with filters and complex queries."""
    
    def __init__(self, db_path: str = "data/indexes/files.db"):
        self.db_path = db_path
        
    def search(
        self,
        query: Optional[str] = None,
        file_types: Optional[List[str]] = None,
        extensions: Optional[List[str]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        size_min: Optional[int] = None,
        size_max: Optional[int] = None,
        has_content: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        is_favorite: Optional[bool] = None,
        path_contains: Optional[str] = None,
        regex_pattern: Optional[str] = None,
        sort_by: str = "relevance",
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Perform advanced search with multiple filters.
        
        Args:
            query: Text to search in filename and content
            file_types: List of file types to filter (document, image, video, etc.)
            extensions: List of file extensions to filter
            date_from: Start date for modified date range
            date_to: End date for modified date range
            size_min: Minimum file size in bytes
            size_max: Maximum file size in bytes
            has_content: Filter for files with/without extracted content
            tags: List of tags to filter by
            is_favorite: Filter for favorite files only
            path_contains: Filter paths containing this text
            regex_pattern: Regex pattern to match filenames
            sort_by: Sort results by (relevance, name, size, date)
            limit: Maximum number of results
            offset: Offset for pagination
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Build dynamic query
            conditions = []
            params = []
            
            # Text search in filename and content
            if query:
                search_condition = """
                    (filename LIKE ? OR 
                     content_text LIKE ? OR
                     path LIKE ?)
                """
                conditions.append(search_condition)
                query_pattern = f"%{query}%"
                params.extend([query_pattern, query_pattern, query_pattern])
            
            # File type filter
            if file_types:
                placeholders = ','.join('?' * len(file_types))
                conditions.append(f"file_type IN ({placeholders})")
                params.extend(file_types)
            
            # Extension filter
            if extensions:
                ext_conditions = []
                for ext in extensions:
                    ext_conditions.append("filename LIKE ?")
                    params.append(f"%{ext}")
                conditions.append(f"({' OR '.join(ext_conditions)})")
            
            # Date range filter
            if date_from:
                conditions.append("modified_at >= ?")
                params.append(date_from.isoformat())
            
            if date_to:
                conditions.append("modified_at <= ?")
                params.append(date_to.isoformat())
            
            # Size range filter
            if size_min is not None:
                conditions.append("size_bytes >= ?")
                params.append(size_min)
            
            if size_max is not None:
                conditions.append("size_bytes <= ?")
                params.append(size_max)
            
            # Content filter
            if has_content is not None:
                if has_content:
                    conditions.append("content_text IS NOT NULL AND content_text != ''")
                else:
                    conditions.append("(content_text IS NULL OR content_text = '')")
            
            # Path contains filter
            if path_contains:
                conditions.append("path LIKE ?")
                params.append(f"%{path_contains}%")
            
            # Build final query
            base_query = """
                SELECT 
                    id,
                    path,
                    filename,
                    file_type,
                    size_bytes,
                    modified_at,
                    content_text,
                    indexed_at,
                    CASE 
                        WHEN content_text IS NOT NULL AND content_text != '' 
                        THEN LENGTH(content_text) 
                        ELSE 0 
                    END as content_length
                FROM files
            """
            
            if conditions:
                where_clause = " WHERE " + " AND ".join(conditions)
            else:
                where_clause = ""
            
            # Add sorting
            order_clause, order_params = self._get_order_clause(sort_by, query)
            
            # Final query with limit and offset
            final_query = f"{base_query}{where_clause}{order_clause} LIMIT ? OFFSET ?"
            params.extend(order_params)  # Add order parameters first
            params.extend([limit, offset])
            
            # Debug logging
            logger.debug(f"Advanced search query: {final_query}")
            logger.debug(f"Parameters ({len(params)}): {params}")
            
            # Execute search
            cursor.execute(final_query, params)
            results = [dict(row) for row in cursor.fetchall()]
            
            # Get total count for pagination
            count_query = f"SELECT COUNT(*) FROM files{where_clause}"
            # Exclude order params, limit and offset
            count_params = params[:-(len(order_params) + 2)]
            logger.debug(f"Count query: {count_query}")
            logger.debug(f"Count params ({len(count_params)}): {count_params}")
            
            cursor.execute(count_query, count_params)
            total_count = cursor.fetchone()[0]
            
            # Apply regex filtering if specified (post-processing)
            if regex_pattern:
                try:
                    pattern = re.compile(regex_pattern, re.IGNORECASE)
                    results = [
                        r for r in results 
                        if pattern.search(r['filename'])
                    ]
                    total_count = len(results)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern: {e}")
            
            # Calculate relevance scores if text search
            if query:
                results = self._calculate_relevance(results, query)
                if sort_by == "relevance":
                    results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
            
            conn.close()
            
            return {
                'success': True,
                'results': results,
                'total_count': total_count,
                'page': offset // limit + 1 if limit > 0 else 1,
                'total_pages': (total_count + limit - 1) // limit if limit > 0 else 1,
                'query_info': {
                    'query': query,
                    'filters_applied': len(conditions),
                    'sort_by': sort_by
                }
            }
        
        except Exception as e:
            logger.error(f"Advanced search error: {e}")
            return {
                'success': False,
                'error': str(e),
                'results': [],
                'total_count': 0
            }
    
    def _get_order_clause(self, sort_by: str, query: Optional[str]) -> Tuple[str, List]:
        """Get ORDER BY clause and parameters based on sort option."""
        if sort_by == "name":
            return " ORDER BY filename ASC", []
        elif sort_by == "size":
            return " ORDER BY size_bytes DESC", []
        elif sort_by == "date":
            return " ORDER BY modified_at DESC", []
        elif sort_by == "relevance" and query:
            # Basic relevance: prioritize filename matches
            return " ORDER BY CASE WHEN filename LIKE ? THEN 0 ELSE 1 END, filename", [f"%{query}%"]
        else:
            return " ORDER BY modified_at DESC", []
    
    def _calculate_relevance(self, results: List[Dict], query: str) -> List[Dict]:
        """Calculate relevance scores for search results."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for result in results:
            score = 0.0
            
            filename = (result.get('filename') or '').lower()
            content = (result.get('content_text') or '').lower()
            path = (result.get('path') or '').lower()
            
            # Exact match in filename (highest priority)
            if query_lower in filename:
                score += 10.0
            
            # Word matches in filename
            filename_words = set(filename.split('.')[0].replace('_', ' ').replace('-', ' ').split())
            matching_words = query_words & filename_words
            score += len(matching_words) * 3.0
            
            # Matches in path
            if query_lower in path:
                score += 2.0
            
            # Matches in content (if available)
            if content:
                # Count occurrences
                occurrences = content.count(query_lower)
                score += min(occurrences * 0.5, 5.0)  # Cap content score
                
                # Word matches in content
                content_words = set(content[:1000].split())  # Check first 1000 chars
                content_matches = query_words & content_words
                score += len(content_matches) * 0.2
            
            result['relevance_score'] = score
        
        return results
    
    def suggest_searches(self, partial_query: str, limit: int = 10) -> List[str]:
        """Get search suggestions based on partial query."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get unique filenames that match
            cursor.execute("""
                SELECT DISTINCT filename
                FROM files
                WHERE filename LIKE ?
                LIMIT ?
            """, (f"%{partial_query}%", limit))
            
            suggestions = [row[0] for row in cursor.fetchall()]
            
            # Extract common terms from filenames
            terms = set()
            for filename in suggestions:
                # Extract words from filename
                name_parts = filename.rsplit('.', 1)[0]  # Remove extension
                words = re.findall(r'\b\w+\b', name_parts)
                terms.update(word.lower() for word in words if len(word) > 2)
            
            # Filter terms that match partial query
            matching_terms = [
                term for term in terms 
                if term.startswith(partial_query.lower())
            ]
            
            conn.close()
            
            return sorted(matching_terms)[:limit]
        
        except Exception as e:
            logger.error(f"Error getting search suggestions: {e}")
            return []
    
    def get_search_stats(self) -> Dict[str, Any]:
        """Get statistics about searchable content."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = {}
            
            # Total files
            cursor.execute("SELECT COUNT(*) FROM files")
            stats['total_files'] = cursor.fetchone()[0]
            
            # Files with content
            cursor.execute("""
                SELECT COUNT(*) 
                FROM files 
                WHERE content_text IS NOT NULL AND content_text != ''
            """)
            stats['files_with_content'] = cursor.fetchone()[0]
            
            # File types distribution
            cursor.execute("""
                SELECT file_type, COUNT(*) as count
                FROM files
                GROUP BY file_type
                ORDER BY count DESC
            """)
            stats['file_types'] = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Top extensions
            cursor.execute("""
                SELECT 
                    LOWER(SUBSTR(filename, INSTR(filename, '.') + 1)) as ext,
                    COUNT(*) as count
                FROM files
                WHERE INSTR(filename, '.') > 0
                GROUP BY ext
                ORDER BY count DESC
                LIMIT 10
            """)
            stats['top_extensions'] = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Date range
            cursor.execute("""
                SELECT 
                    MIN(modified_at) as oldest,
                    MAX(modified_at) as newest
                FROM files
            """)
            row = cursor.fetchone()
            stats['date_range'] = {
                'oldest': row[0],
                'newest': row[1]
            }
            
            # Size distribution
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN size_bytes < 1024*1024 THEN 1 END) as small,
                    COUNT(CASE WHEN size_bytes >= 1024*1024 AND size_bytes < 10*1024*1024 THEN 1 END) as medium,
                    COUNT(CASE WHEN size_bytes >= 10*1024*1024 AND size_bytes < 100*1024*1024 THEN 1 END) as large,
                    COUNT(CASE WHEN size_bytes >= 100*1024*1024 THEN 1 END) as huge
                FROM files
            """)
            row = cursor.fetchone()
            stats['size_distribution'] = {
                'small_(<1MB)': row[0],
                'medium_(1-10MB)': row[1],
                'large_(10-100MB)': row[2],
                'huge_(>100MB)': row[3]
            }
            
            conn.close()
            
            return stats
        
        except Exception as e:
            logger.error(f"Error getting search stats: {e}")
            return {}