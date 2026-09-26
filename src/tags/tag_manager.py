"""Tag and favorites management system."""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
import json

from loguru import logger


class TagManager:
    """Manage tags and favorites for files."""
    
    def __init__(self, db_path=None):
        from ..core.database import default_db_path
        self.db_path = db_path or default_db_path()
        self._init_tables()
    
    def _init_tables(self):
        """Initialize tags and favorites tables."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Tags table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    color TEXT DEFAULT '#007ACC',
                    description TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    usage_count INTEGER DEFAULT 0
                )
            """)
            
            # File tags relationship table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_tags (
                    file_id INTEGER,
                    tag_id INTEGER,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (file_id, tag_id),
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                )
            """)
            
            # Favorites table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    file_id INTEGER PRIMARY KEY,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT DEFAULT '',
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_tags_file_id ON file_tags(file_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_tags_tag_id ON file_tags(tag_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)")
            
            conn.commit()
            conn.close()
            
            logger.info("Tag system tables initialized")
            
        except Exception as e:
            logger.error(f"Error initializing tag tables: {e}")
    
    # Tag Management
    def create_tag(self, name: str, color: str = "#007ACC", description: str = "") -> Optional[int]:
        """Create a new tag."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO tags (name, color, description)
                VALUES (?, ?, ?)
            """, (name.strip(), color, description))
            
            tag_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            logger.info(f"Created tag '{name}' with ID {tag_id}")
            return tag_id
            
        except sqlite3.IntegrityError:
            logger.warning(f"Tag '{name}' already exists")
            return None
        except Exception as e:
            logger.error(f"Error creating tag: {e}")
            return None
    
    def get_tags(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all tags, optionally filtered by search term."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if search:
                cursor.execute("""
                    SELECT t.*, COUNT(ft.file_id) as file_count
                    FROM tags t
                    LEFT JOIN file_tags ft ON t.id = ft.tag_id
                    WHERE t.name LIKE ? OR t.description LIKE ?
                    GROUP BY t.id
                    ORDER BY t.usage_count DESC, t.name
                """, (f"%{search}%", f"%{search}%"))
            else:
                cursor.execute("""
                    SELECT t.*, COUNT(ft.file_id) as file_count
                    FROM tags t
                    LEFT JOIN file_tags ft ON t.id = ft.tag_id
                    GROUP BY t.id
                    ORDER BY t.usage_count DESC, t.name
                """)
            
            tags = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return tags
            
        except Exception as e:
            logger.error(f"Error getting tags: {e}")
            return []
    
    def update_tag(self, tag_id: int, name: Optional[str] = None, 
                   color: Optional[str] = None, description: Optional[str] = None) -> bool:
        """Update tag properties."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = ?")
                params.append(name.strip())
            
            if color is not None:
                updates.append("color = ?")
                params.append(color)
            
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            
            if not updates:
                return False
            
            params.append(tag_id)
            
            cursor.execute(f"""
                UPDATE tags 
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            return success
            
        except Exception as e:
            logger.error(f"Error updating tag: {e}")
            return False
    
    def delete_tag(self, tag_id: int) -> bool:
        """Delete a tag and remove all its associations."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Delete tag (file_tags will be deleted by CASCADE)
            cursor.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            if success:
                logger.info(f"Deleted tag {tag_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error deleting tag: {e}")
            return False
    
    # File Tagging
    def add_tag_to_file(self, file_id: int, tag_id: int) -> bool:
        """Add a tag to a file."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Add tag relationship
            cursor.execute("""
                INSERT OR IGNORE INTO file_tags (file_id, tag_id)
                VALUES (?, ?)
            """, (file_id, tag_id))
            
            # Update usage count
            cursor.execute("""
                UPDATE tags 
                SET usage_count = usage_count + 1 
                WHERE id = ?
            """, (tag_id,))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            return success
            
        except Exception as e:
            logger.error(f"Error adding tag to file: {e}")
            return False
    
    def remove_tag_from_file(self, file_id: int, tag_id: int) -> bool:
        """Remove a tag from a file."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Remove tag relationship
            cursor.execute("""
                DELETE FROM file_tags 
                WHERE file_id = ? AND tag_id = ?
            """, (file_id, tag_id))
            
            if cursor.rowcount > 0:
                # Update usage count
                cursor.execute("""
                    UPDATE tags 
                    SET usage_count = MAX(0, usage_count - 1) 
                    WHERE id = ?
                """, (tag_id,))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            return success
            
        except Exception as e:
            logger.error(f"Error removing tag from file: {e}")
            return False
    
    def get_file_tags(self, file_id: int) -> List[Dict[str, Any]]:
        """Get all tags for a specific file."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT t.*, ft.added_at as tagged_at
                FROM tags t
                JOIN file_tags ft ON t.id = ft.tag_id
                WHERE ft.file_id = ?
                ORDER BY t.name
            """, (file_id,))
            
            tags = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return tags
            
        except Exception as e:
            logger.error(f"Error getting file tags: {e}")
            return []
    
    def get_files_by_tag(self, tag_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all files with a specific tag."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT f.*, ft.added_at as tagged_at
                FROM files f
                JOIN file_tags ft ON f.id = ft.file_id
                WHERE ft.tag_id = ?
                ORDER BY ft.added_at DESC
                LIMIT ?
            """, (tag_id, limit))
            
            files = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return files
            
        except Exception as e:
            logger.error(f"Error getting files by tag: {e}")
            return []
    
    def search_files_by_tags(self, tag_names: List[str], match_all: bool = False) -> List[Dict[str, Any]]:
        """Search files by tag names."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if match_all:
                # Files that have ALL specified tags
                placeholders = ','.join('?' * len(tag_names))
                cursor.execute(f"""
                    SELECT f.*
                    FROM files f
                    WHERE f.id IN (
                        SELECT ft.file_id
                        FROM file_tags ft
                        JOIN tags t ON ft.tag_id = t.id
                        WHERE t.name IN ({placeholders})
                        GROUP BY ft.file_id
                        HAVING COUNT(DISTINCT t.id) = ?
                    )
                    ORDER BY f.modified_at DESC
                """, tag_names + [len(tag_names)])
            else:
                # Files that have ANY of the specified tags
                placeholders = ','.join('?' * len(tag_names))
                cursor.execute(f"""
                    SELECT DISTINCT f.*
                    FROM files f
                    JOIN file_tags ft ON f.id = ft.file_id
                    JOIN tags t ON ft.tag_id = t.id
                    WHERE t.name IN ({placeholders})
                    ORDER BY f.modified_at DESC
                """, tag_names)
            
            files = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return files
            
        except Exception as e:
            logger.error(f"Error searching files by tags: {e}")
            return []
    
    # Favorites Management
    def add_to_favorites(self, file_id: int, notes: str = "") -> bool:
        """Add a file to favorites."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO favorites (file_id, notes, added_at)
                VALUES (?, ?, ?)
            """, (file_id, notes, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Added file {file_id} to favorites")
            return True
            
        except Exception as e:
            logger.error(f"Error adding to favorites: {e}")
            return False
    
    def remove_from_favorites(self, file_id: int) -> bool:
        """Remove a file from favorites."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM favorites WHERE file_id = ?", (file_id,))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            if success:
                logger.info(f"Removed file {file_id} from favorites")
            
            return success
            
        except Exception as e:
            logger.error(f"Error removing from favorites: {e}")
            return False
    
    def is_favorite(self, file_id: int) -> bool:
        """Check if a file is in favorites."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT 1 FROM favorites WHERE file_id = ?", (file_id,))
            result = cursor.fetchone() is not None
            
            conn.close()
            return result
            
        except Exception as e:
            logger.error(f"Error checking favorite status: {e}")
            return False
    
    def get_favorites(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all favorite files."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT f.*, fav.added_at as favorited_at, fav.notes as favorite_notes
                FROM files f
                JOIN favorites fav ON f.id = fav.file_id
                ORDER BY fav.added_at DESC
                LIMIT ?
            """, (limit,))
            
            favorites = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return favorites
            
        except Exception as e:
            logger.error(f"Error getting favorites: {e}")
            return []
    
    def update_favorite_notes(self, file_id: int, notes: str) -> bool:
        """Update notes for a favorite file."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE favorites 
                SET notes = ? 
                WHERE file_id = ?
            """, (notes, file_id))
            
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            
            return success
            
        except Exception as e:
            logger.error(f"Error updating favorite notes: {e}")
            return False
    
    # Smart Suggestions
    def suggest_tags_for_file(self, file_path: str, content: Optional[str] = None) -> List[str]:
        """Suggest tags for a file based on path and content."""
        suggestions = set()
        
        file_path = Path(file_path)
        
        # Path-based suggestions
        path_parts = file_path.parts
        for part in path_parts:
            if len(part) > 2 and not part.startswith('.'):
                # Clean up path part
                clean_part = part.replace('_', ' ').replace('-', ' ').lower()
                if clean_part not in ['documents', 'files', 'data', 'src', 'bin']:
                    suggestions.add(clean_part)
        
        # Extension-based suggestions
        ext = file_path.suffix.lower()
        if ext:
            type_mapping = {
                '.pdf': 'document',
                '.doc': 'document', '.docx': 'document',
                '.xls': 'spreadsheet', '.xlsx': 'spreadsheet',
                '.ppt': 'presentation', '.pptx': 'presentation',
                '.jpg': 'image', '.png': 'image', '.gif': 'image',
                '.mp4': 'video', '.avi': 'video', '.mov': 'video',
                '.mp3': 'audio', '.wav': 'audio',
                '.py': 'code', '.js': 'code', '.java': 'code',
                '.txt': 'text', '.md': 'text',
                '.zip': 'archive', '.rar': 'archive'
            }
            
            if ext in type_mapping:
                suggestions.add(type_mapping[ext])
        
        # Content-based suggestions (basic keyword extraction)
        if content:
            content_lower = content.lower()
            keywords = [
                'report', 'contract', 'invoice', 'receipt', 'letter',
                'meeting', 'project', 'proposal', 'budget', 'financial',
                'technical', 'specification', 'manual', 'guide', 'tutorial'
            ]
            
            for keyword in keywords:
                if keyword in content_lower:
                    suggestions.add(keyword)
        
        return list(suggestions)[:10]  # Limit to 10 suggestions
    
    def get_popular_tags(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get most popular tags by usage."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT t.*, COUNT(ft.file_id) as file_count
                FROM tags t
                LEFT JOIN file_tags ft ON t.id = ft.tag_id
                GROUP BY t.id
                HAVING t.usage_count > 0
                ORDER BY t.usage_count DESC, file_count DESC
                LIMIT ?
            """, (limit,))
            
            tags = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return tags
            
        except Exception as e:
            logger.error(f"Error getting popular tags: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tag and favorites statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = {}
            
            # Tag stats
            cursor.execute("SELECT COUNT(*) FROM tags")
            stats['total_tags'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT file_id) FROM file_tags")
            stats['tagged_files'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM file_tags")
            stats['total_tag_relations'] = cursor.fetchone()[0]
            
            # Average tags per file
            if stats['tagged_files'] > 0:
                stats['avg_tags_per_file'] = stats['total_tag_relations'] / stats['tagged_files']
            else:
                stats['avg_tags_per_file'] = 0
            
            # Favorites stats
            cursor.execute("SELECT COUNT(*) FROM favorites")
            stats['total_favorites'] = cursor.fetchone()[0]
            
            # Most used tag
            cursor.execute("""
                SELECT name, usage_count 
                FROM tags 
                ORDER BY usage_count DESC 
                LIMIT 1
            """)
            top_tag = cursor.fetchone()
            if top_tag:
                stats['most_used_tag'] = {'name': top_tag[0], 'usage_count': top_tag[1]}
            else:
                stats['most_used_tag'] = None
            
            conn.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting tag stats: {e}")
            return {}