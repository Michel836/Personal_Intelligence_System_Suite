"""Analytics dashboard for 36TB Intelligence."""

import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import json
from dataclasses import dataclass

from loguru import logger


@dataclass
class FileStats:
    """File statistics data structure."""
    total_files: int = 0
    total_size: int = 0
    by_type: Dict[str, int] = None
    by_size_range: Dict[str, int] = None
    recent_files: List[Dict] = None
    largest_files: List[Dict] = None
    
    def __post_init__(self):
        if self.by_type is None:
            self.by_type = {}
        if self.by_size_range is None:
            self.by_size_range = {}
        if self.recent_files is None:
            self.recent_files = []
        if self.largest_files is None:
            self.largest_files = []


class AnalyticsDashboard:
    """Analytics dashboard for file collection insights."""
    
    def __init__(self, db_path=None):
        from ..core.database import default_db_path
        self.db_path = db_path or default_db_path()
        
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)
    
    def get_overview_stats(self) -> FileStats:
        """Get comprehensive file statistics."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                stats = FileStats()
                
                # Total files and size
                cursor.execute("""
                    SELECT COUNT(*), SUM(CAST(size_bytes AS INTEGER))
                    FROM files 
                    WHERE size_bytes IS NOT NULL AND size_bytes > 0
                """)
                result = cursor.fetchone()
                stats.total_files = result[0] or 0
                stats.total_size = result[1] or 0
                
                # Files by type
                cursor.execute("""
                    SELECT file_type, COUNT(*) as count
                    FROM files 
                    GROUP BY file_type 
                    ORDER BY count DESC
                    LIMIT 15
                """)
                stats.by_type = dict(cursor.fetchall())
                
                # Files by size range
                size_ranges = [
                    ("0-1KB", 0, 1024),
                    ("1KB-100KB", 1024, 100*1024),
                    ("100KB-1MB", 100*1024, 1024*1024),
                    ("1MB-10MB", 1024*1024, 10*1024*1024),
                    ("10MB-100MB", 10*1024*1024, 100*1024*1024),
                    ("100MB-1GB", 100*1024*1024, 1024*1024*1024),
                    ("1GB+", 1024*1024*1024, float('inf'))
                ]
                
                for range_name, min_size, max_size in size_ranges:
                    if max_size == float('inf'):
                        cursor.execute("""
                            SELECT COUNT(*) FROM files 
                            WHERE size_bytes >= ? AND size_bytes IS NOT NULL AND size_bytes > 0
                        """, (min_size,))
                    else:
                        cursor.execute("""
                            SELECT COUNT(*) FROM files 
                            WHERE size_bytes >= ? AND size_bytes < ? 
                            AND size_bytes IS NOT NULL AND size_bytes > 0
                        """, (min_size, max_size))
                    
                    count = cursor.fetchone()[0] or 0
                    if count > 0:
                        stats.by_size_range[range_name] = count
                
                # Recent files (last 30 days)
                thirty_days_ago = datetime.now() - timedelta(days=30)
                cursor.execute("""
                    SELECT path, filename, file_type, size_bytes, modified_at
                    FROM files 
                    WHERE datetime(modified_at) >= ?
                    ORDER BY datetime(modified_at) DESC
                    LIMIT 20
                """, (thirty_days_ago.isoformat(),))
                
                stats.recent_files = [
                    {
                        'path': row[0],
                        'name': row[1],
                        'type': row[2],
                        'size': row[3] or 0,
                        'modified': row[4]
                    }
                    for row in cursor.fetchall()
                ]
                
                # Largest files
                cursor.execute("""
                    SELECT path, filename, file_type, size_bytes, modified_at
                    FROM files 
                    WHERE size_bytes IS NOT NULL AND size_bytes > 0
                    ORDER BY size_bytes DESC
                    LIMIT 20
                """)
                
                stats.largest_files = [
                    {
                        'path': row[0],
                        'name': row[1],
                        'type': row[2],
                        'size': row[3] or 0,
                        'modified': row[4]
                    }
                    for row in cursor.fetchall()
                ]
                
                return stats
                
        except Exception as e:
            logger.error(f"Error getting overview stats: {e}")
            return FileStats()
    
    def get_type_distribution(self, limit: int = 20) -> List[Tuple[str, int, float]]:
        """Get file type distribution with percentages."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get total count first
                cursor.execute("SELECT COUNT(*) FROM files")
                total = cursor.fetchone()[0] or 1
                
                # Get distribution
                cursor.execute("""
                    SELECT file_type, COUNT(*) as count
                    FROM files 
                    GROUP BY file_type 
                    ORDER BY count DESC
                    LIMIT ?
                """, (limit,))
                
                results = []
                for type_name, count in cursor.fetchall():
                    percentage = (count / total) * 100
                    results.append((type_name or 'Unknown', count, percentage))
                
                return results
                
        except Exception as e:
            logger.error(f"Error getting type distribution: {e}")
            return []
    
    def get_size_distribution(self) -> Dict[str, Dict[str, Any]]:
        """Get detailed size distribution analysis."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Size statistics
                cursor.execute("""
                    SELECT 
                        AVG(size_bytes) as avg_size,
                        MIN(size_bytes) as min_size,
                        MAX(size_bytes) as max_size,
                        COUNT(*) as total_files
                    FROM files 
                    WHERE size_bytes IS NOT NULL AND size_bytes > 0
                """)
                
                result = cursor.fetchone()
                
                return {
                    'avg_size': int(result[0]) if result[0] else 0,
                    'min_size': int(result[1]) if result[1] else 0,
                    'max_size': int(result[2]) if result[2] else 0,
                    'total_files': result[3] or 0
                }
                
        except Exception as e:
            logger.error(f"Error getting size distribution: {e}")
            return {}
    
    def get_timeline_stats(self, days: int = 30) -> Dict[str, int]:
        """Get file modification timeline."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get files modified in the last N days, grouped by date
                cursor.execute("""
                    SELECT date(modified_at) as mod_date, COUNT(*) as count
                    FROM files 
                    WHERE datetime(modified_at) >= datetime('now', '-' || ? || ' days')
                    GROUP BY date(modified_at)
                    ORDER BY mod_date DESC
                """, (days,))
                
                return dict(cursor.fetchall())
                
        except Exception as e:
            logger.error(f"Error getting timeline stats: {e}")
            return {}
    
    def get_directory_stats(self, limit: int = 15) -> List[Tuple[str, int, int]]:
        """Get top directories by file count and size."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Extract directory from path and group
                cursor.execute("""
                    SELECT 
                        COALESCE(parent_dir, 'Root') as directory,
                        COUNT(*) as file_count,
                        SUM(CASE WHEN size_bytes IS NOT NULL THEN size_bytes ELSE 0 END) as total_size
                    FROM files 
                    GROUP BY parent_dir
                    ORDER BY file_count DESC
                    LIMIT ?
                """, (limit,))
                
                return cursor.fetchall()
                
        except Exception as e:
            logger.error(f"Error getting directory stats: {e}")
            return []
    
    def get_search_insights(self) -> Dict[str, Any]:
        """Get insights for search optimization."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                insights = {}
                
                # Files with extracted content (searchable)
                cursor.execute("""
                    SELECT COUNT(*) FROM files WHERE content_text IS NOT NULL AND content_text != ''
                """)
                insights['searchable_files'] = cursor.fetchone()[0] or 0
                
                # Files without content extraction
                cursor.execute("""
                    SELECT COUNT(*) FROM files WHERE content_text IS NULL OR content_text = ''
                """)
                insights['non_searchable_files'] = cursor.fetchone()[0] or 0
                
                # Most common file extensions for potential extraction
                cursor.execute("""
                    SELECT file_type, COUNT(*) as count
                    FROM files 
                    WHERE (content_text IS NULL OR content_text = '') 
                    AND file_type IN ('pdf', 'docx', 'doc', 'txt', 'rtf', 'pptx', 'ppt')
                    GROUP BY file_type
                    ORDER BY count DESC
                    LIMIT 10
                """)
                insights['extraction_opportunities'] = dict(cursor.fetchall())
                
                return insights
                
        except Exception as e:
            logger.error(f"Error getting search insights: {e}")
            return {}
    
    def format_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes == 0:
            return "0 B"
        
        units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit_index = 0
        size = float(size_bytes)
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        else:
            return f"{size:.1f} {units[unit_index]}"
    
    def export_stats(self, output_path: Optional[str] = None) -> str:
        """Export analytics to JSON file."""
        try:
            stats = self.get_overview_stats()
            type_dist = self.get_type_distribution()
            size_dist = self.get_size_distribution()
            timeline = self.get_timeline_stats()
            directory_stats = self.get_directory_stats()
            search_insights = self.get_search_insights()
            
            export_data = {
                'generated_at': datetime.now().isoformat(),
                'overview': {
                    'total_files': stats.total_files,
                    'total_size': stats.total_size,
                    'total_size_formatted': self.format_size(stats.total_size)
                },
                'type_distribution': [
                    {'type': t, 'count': c, 'percentage': p}
                    for t, c, p in type_dist
                ],
                'size_distribution': size_dist,
                'timeline': timeline,
                'directory_stats': [
                    {'directory': d, 'file_count': c, 'total_size': s}
                    for d, c, s in directory_stats
                ],
                'search_insights': search_insights
            }
            
            if not output_path:
                output_path = f"data/reports/analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Analytics exported to: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error exporting stats: {e}")
            return ""