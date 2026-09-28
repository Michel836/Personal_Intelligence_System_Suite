"""Advanced search system with multiple filters and options."""

import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import re

from loguru import logger


class AdvancedSearch:
    """Advanced search system with filters and complex queries."""

    def __init__(self, db_path=None):
        from ..core.database import default_db_path
        self.db_path = db_path or default_db_path()

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
        offset: int = 0,
        include_missing: bool = False,
    ) -> Dict[str, Any]:
        """Perform advanced search with multiple filters.

        Missing lifecycle rows are hidden by default so advanced search has the
        same user-visible semantics as the canonical lexical search.
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            conditions = []
            params = []

            if not include_missing:
                conditions.append("COALESCE(state, 'ACTIVE') = 'ACTIVE'")

            if query:
                conditions.append(
                    "(filename LIKE ? OR content_text LIKE ? OR path LIKE ?)"
                )
                query_pattern = f"%{query}%"
                params.extend([query_pattern, query_pattern, query_pattern])

            if file_types:
                placeholders = ','.join('?' * len(file_types))
                conditions.append(f"file_type IN ({placeholders})")
                params.extend(file_types)

            if extensions:
                ext_conditions = []
                for ext in extensions:
                    ext_conditions.append("filename LIKE ?")
                    params.append(f"%{ext}")
                conditions.append(f"({' OR '.join(ext_conditions)})")

            if date_from:
                conditions.append("modified_at >= ?")
                params.append(date_from.isoformat())
            if date_to:
                conditions.append("modified_at <= ?")
                params.append(date_to.isoformat())
            if size_min is not None:
                conditions.append("size_bytes >= ?")
                params.append(size_min)
            if size_max is not None:
                conditions.append("size_bytes <= ?")
                params.append(size_max)

            if has_content is not None:
                if has_content:
                    conditions.append("content_text IS NOT NULL AND content_text != ''")
                else:
                    conditions.append("(content_text IS NULL OR content_text = '')")

            if path_contains:
                conditions.append("path LIKE ?")
                params.append(f"%{path_contains}%")

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

            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            order_clause, order_params = self._get_order_clause(sort_by, query)
            final_query = f"{base_query}{where_clause}{order_clause} LIMIT ? OFFSET ?"
            search_params = list(params) + list(order_params) + [limit, offset]

            logger.debug(f"Advanced search query: {final_query}")
            cursor.execute(final_query, search_params)
            results = [dict(row) for row in cursor.fetchall()]

            count_query = f"SELECT COUNT(*) FROM files{where_clause}"
            cursor.execute(count_query, params)
            total_count = int(cursor.fetchone()[0])

            if regex_pattern:
                try:
                    pattern = re.compile(regex_pattern, re.IGNORECASE)
                    results = [r for r in results if pattern.search(r['filename'])]
                    # Regex filtering is post-query, so this count describes the
                    # returned page rather than pretending to be a global count.
                    total_count = len(results)
                except re.error as exc:
                    logger.warning(f"Invalid regex pattern: {exc}")

            if query:
                results = self._calculate_relevance(results, query)
                if sort_by == "relevance":
                    results.sort(
                        key=lambda x: x.get('relevance_score', 0), reverse=True
                    )

            return {
                'success': True,
                'results': results,
                'total_count': total_count,
                'page': offset // limit + 1 if limit > 0 else 1,
                'total_pages': (total_count + limit - 1) // limit if limit > 0 else 1,
                'query_info': {
                    'query': query,
                    'filters_applied': len(conditions),
                    'sort_by': sort_by,
                    'include_missing': include_missing,
                }
            }

        except Exception as exc:
            logger.error(f"Advanced search error: {exc}")
            return {
                'success': False,
                'error': str(exc),
                'results': [],
                'total_count': 0,
            }
        finally:
            if conn is not None:
                conn.close()

    def _get_order_clause(self, sort_by: str, query: Optional[str]) -> Tuple[str, List]:
        if sort_by == "name":
            return " ORDER BY filename ASC", []
        if sort_by == "size":
            return " ORDER BY size_bytes DESC", []
        if sort_by == "date":
            return " ORDER BY modified_at DESC", []
        if sort_by == "relevance" and query:
            return (
                " ORDER BY CASE WHEN filename LIKE ? THEN 0 ELSE 1 END, filename",
                [f"%{query}%"],
            )
        return " ORDER BY modified_at DESC", []

    def _calculate_relevance(self, results: List[Dict], query: str) -> List[Dict]:
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for result in results:
            score = 0.0
            filename = (result.get('filename') or '').lower()
            content = (result.get('content_text') or '').lower()
            path = (result.get('path') or '').lower()

            if query_lower in filename:
                score += 10.0
            if query_lower in path:
                score += 3.0
            if query_lower in content:
                score += 2.0

            filename_words = set(re.findall(r'\w+', filename))
            content_words = set(re.findall(r'\w+', content))
            path_words = set(re.findall(r'\w+', path))
            score += len(query_words & filename_words) * 3.0
            score += len(query_words & path_words) * 1.0
            score += len(query_words & content_words) * 0.5
            result['relevance_score'] = score

        return results
