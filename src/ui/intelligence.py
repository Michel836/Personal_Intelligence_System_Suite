"""Contextual intelligence features for 36TB Intelligence."""

import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import json
import hashlib
from collections import defaultdict, Counter
import re

class ContextualIntelligence:
    """Smart contextual features and insights."""
    
    def __init__(self):
        self.insights_cache = {}
        self.usage_patterns = defaultdict(int)
        self.recommendations_cache = {}
        
    def get_smart_recommendations(self, user_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate intelligent recommendations based on user behavior."""
        recommendations = []
        
        try:
            # Recent activity patterns
            recent_files = self._get_recent_activity()
            file_types = self._analyze_file_types(recent_files)
            
            # Time-based recommendations
            current_hour = datetime.now().hour
            if 9 <= current_hour <= 17:  # Work hours
                recommendations.extend(self._get_work_recommendations(file_types))
            else:  # Personal time
                recommendations.extend(self._get_personal_recommendations(file_types))
            
            # Storage optimization suggestions
            storage_suggestions = self._get_storage_suggestions()
            recommendations.extend(storage_suggestions)
            
            # Duplicate detection
            duplicate_suggestions = self._get_duplicate_suggestions()
            recommendations.extend(duplicate_suggestions)
            
            # Learning patterns
            learning_suggestions = self._get_learning_suggestions()
            recommendations.extend(learning_suggestions)
            
        except Exception as e:
            st.error(f"Error generating recommendations: {e}")
        
        return recommendations[:10]  # Top 10 recommendations
    
    def analyze_document_relationships(self, file_path: str) -> Dict[str, Any]:
        """Analyze relationships between documents."""
        try:
            # Extract file info
            path_obj = Path(file_path)
            file_name = path_obj.name
            file_dir = path_obj.parent
            file_ext = path_obj.suffix.lower()
            
            relationships = {
                'similar_files': [],
                'related_directories': [],
                'version_files': [],
                'companion_files': [],
                'reference_score': 0
            }
            
            # Find similar files in same directory
            try:
                for sibling in file_dir.iterdir():
                    if sibling.is_file() and sibling != path_obj:
                        similarity = self._calculate_file_similarity(file_name, sibling.name)
                        if similarity > 0.7:
                            relationships['similar_files'].append({
                                'path': str(sibling),
                                'similarity': similarity,
                                'reason': self._get_similarity_reason(file_name, sibling.name)
                            })
            except:
                pass
            
            # Find version files (same name, different numbers/dates)
            version_pattern = re.compile(r'(.+?)[-_\s]*(?:v\d+|\d+|copy|final|draft)', re.IGNORECASE)
            base_name = version_pattern.match(file_name)
            if base_name:
                base = base_name.group(1).lower()
                relationships['version_files'] = self._find_version_files(base, file_dir)
            
            # Find companion files (same name, different extension)
            name_without_ext = path_obj.stem
            companions = self._find_companion_files(name_without_ext, file_dir, file_ext)
            relationships['companion_files'] = companions
            
            # Calculate reference score
            relationships['reference_score'] = self._calculate_reference_score(relationships)
            
            return relationships
            
        except Exception as e:
            return {'error': str(e)}
    
    def get_productivity_insights(self) -> Dict[str, Any]:
        """Generate productivity insights from user patterns."""
        insights = {
            'peak_hours': self._analyze_peak_activity_hours(),
            'file_type_usage': self._analyze_file_type_patterns(),
            'project_focus': self._analyze_project_focus(),
            'efficiency_score': self._calculate_efficiency_score(),
            'suggestions': self._get_productivity_suggestions()
        }
        
        return insights
    
    def detect_duplicate_files(self, threshold: float = 0.95) -> List[Dict[str, Any]]:
        """Detect potential duplicate files."""
        duplicates = []
        
        try:
            # Get all files from database
            all_files = st.session_state.db.get_all_files(limit=1000)
            
            # Group by size first (performance optimization)
            size_groups = defaultdict(list)
            for file_info in all_files:
                size = file_info.get('size_bytes', 0)
                if size > 1024:  # Ignore very small files
                    size_groups[size].append(file_info)
            
            # Check for duplicates within size groups
            for size, files in size_groups.items():
                if len(files) > 1:
                    # Compare file names and paths for similarity
                    for i, file1 in enumerate(files):
                        for file2 in files[i+1:]:
                            similarity = self._calculate_duplicate_probability(file1, file2)
                            
                            if similarity >= threshold:
                                duplicates.append({
                                    'files': [file1, file2],
                                    'similarity': similarity,
                                    'size': size,
                                    'potential_savings': size,
                                    'confidence': self._calculate_confidence_score(file1, file2)
                                })
            
        except Exception as e:
            st.error(f"Error detecting duplicates: {e}")
        
        return sorted(duplicates, key=lambda x: x['similarity'], reverse=True)[:20]
    
    def generate_auto_tags(self, file_path: str, content: str = None) -> List[str]:
        """Generate automatic tags for a file based on its properties."""
        tags = []
        path_obj = Path(file_path)
        
        try:
            # File type tags
            ext = path_obj.suffix.lower()
            type_tags = {
                '.pdf': ['document', 'pdf'],
                '.doc': ['document', 'word'],
                '.docx': ['document', 'word'],
                '.txt': ['text', 'document'],
                '.py': ['code', 'python'],
                '.js': ['code', 'javascript'],
                '.html': ['code', 'web'],
                '.css': ['code', 'web', 'style'],
                '.jpg': ['image', 'photo'],
                '.png': ['image'],
                '.mp4': ['video'],
                '.mp3': ['audio', 'music']
            }
            
            if ext in type_tags:
                tags.extend(type_tags[ext])
            
            # Directory-based tags
            path_parts = path_obj.parts
            for part in path_parts:
                part_lower = part.lower()
                if any(keyword in part_lower for keyword in ['project', 'work', 'document']):
                    tags.append('work')
                elif any(keyword in part_lower for keyword in ['photo', 'image', 'picture']):
                    tags.append('media')
                elif any(keyword in part_lower for keyword in ['download', 'temp', 'tmp']):
                    tags.append('temporary')
            
            # Filename-based tags
            filename_lower = path_obj.name.lower()
            
            # Date patterns
            date_patterns = [
                r'\d{4}[-_]\d{2}[-_]\d{2}',  # YYYY-MM-DD
                r'\d{2}[-_]\d{2}[-_]\d{4}',  # DD-MM-YYYY
                r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)',  # Month names
            ]
            
            for pattern in date_patterns:
                if re.search(pattern, filename_lower):
                    tags.append('dated')
                    break
            
            # Version patterns
            version_patterns = [
                r'v\d+',
                r'version',
                r'draft',
                r'final',
                r'copy'
            ]
            
            for pattern in version_patterns:
                if re.search(pattern, filename_lower):
                    tags.append('versioned')
                    break
            
            # Content-based tags (if content provided)
            if content:
                content_lower = content.lower()
                
                # Technical keywords
                if any(word in content_lower for word in ['function', 'class', 'import', 'def']):
                    tags.append('code')
                
                # Business keywords
                if any(word in content_lower for word in ['meeting', 'project', 'deadline', 'task']):
                    tags.append('business')
                
                # Research keywords
                if any(word in content_lower for word in ['research', 'analysis', 'study', 'data']):
                    tags.append('research')
            
            # Size-based tags
            size = path_obj.stat().st_size if path_obj.exists() else 0
            if size > 100 * 1024 * 1024:  # > 100MB
                tags.append('large-file')
            elif size < 1024:  # < 1KB
                tags.append('small-file')
            
        except Exception as e:
            st.error(f"Error generating auto-tags: {e}")
        
        return list(set(tags))  # Remove duplicates
    
    def _get_recent_activity(self) -> List[Dict[str, Any]]:
        """Get recent file activity."""
        try:
            return st.session_state.db.get_recent_files(limit=50)
        except:
            return []
    
    def _analyze_file_types(self, files: List[Dict[str, Any]]) -> Counter:
        """Analyze file type distribution."""
        file_types = Counter()
        for file_info in files:
            file_type = file_info.get('file_type', 'unknown')
            file_types[file_type] += 1
        return file_types
    
    def _get_work_recommendations(self, file_types: Counter) -> List[Dict[str, Any]]:
        """Get work-hour recommendations."""
        recommendations = []
        
        if file_types.get('document', 0) > 5:
            recommendations.append({
                'type': 'productivity',
                'title': 'Document Organization',
                'description': 'You work with many documents. Consider organizing them with tags.',
                'action': 'organize_documents',
                'priority': 'medium'
            })
        
        if file_types.get('code', 0) > 3:
            recommendations.append({
                'type': 'development',
                'title': 'Code Backup',
                'description': 'Ensure your code is backed up to cloud storage.',
                'action': 'backup_code',
                'priority': 'high'
            })
        
        return recommendations
    
    def _get_personal_recommendations(self, file_types: Counter) -> List[Dict[str, Any]]:
        """Get personal-time recommendations."""
        recommendations = []
        
        if file_types.get('image', 0) > 10:
            recommendations.append({
                'type': 'media',
                'title': 'Photo Organization',
                'description': 'Consider organizing your photos by date or event.',
                'action': 'organize_photos',
                'priority': 'low'
            })
        
        return recommendations
    
    def _get_storage_suggestions(self) -> List[Dict[str, Any]]:
        """Get storage optimization suggestions."""
        suggestions = []
        
        try:
            # Check for large files
            large_files = st.session_state.db.search_files(min_size=100*1024*1024, limit=10)
            if large_files:
                total_size = sum(f.get('size_bytes', 0) for f in large_files)
                suggestions.append({
                    'type': 'storage',
                    'title': 'Large Files Detected',
                    'description': f'Found {len(large_files)} files over 100MB totaling {self._format_size(total_size)}',
                    'action': 'review_large_files',
                    'priority': 'medium'
                })
        except:
            pass
        
        return suggestions
    
    def _get_duplicate_suggestions(self) -> List[Dict[str, Any]]:
        """Get duplicate file suggestions."""
        suggestions = []
        
        duplicates = self.detect_duplicate_files(threshold=0.8)
        if duplicates:
            total_savings = sum(d['potential_savings'] for d in duplicates)
            suggestions.append({
                'type': 'cleanup',
                'title': 'Potential Duplicates Found',
                'description': f'Found {len(duplicates)} potential duplicates. Potential savings: {self._format_size(total_savings)}',
                'action': 'review_duplicates',
                'priority': 'medium'
            })
        
        return suggestions
    
    def _get_learning_suggestions(self) -> List[Dict[str, Any]]:
        """Get learning-based suggestions."""
        suggestions = []
        
        # Suggest features user hasn't used
        if not st.session_state.get('used_ai_search', False):
            suggestions.append({
                'type': 'feature',
                'title': 'Try AI Search',
                'description': 'Use semantic search to find files by meaning, not just filename.',
                'action': 'try_ai_search',
                'priority': 'low'
            })
        
        if not st.session_state.get('used_visualizations', False):
            suggestions.append({
                'type': 'feature',
                'title': 'Explore Visualizations',
                'description': 'See your files in 3D space and discover hidden patterns.',
                'action': 'try_visualizations',
                'priority': 'low'
            })
        
        return suggestions
    
    def _calculate_file_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two filenames."""
        # Simple similarity based on common characters and structure
        name1_clean = re.sub(r'[^a-zA-Z0-9]', '', name1.lower())
        name2_clean = re.sub(r'[^a-zA-Z0-9]', '', name2.lower())
        
        # Jaccard similarity
        set1 = set(name1_clean)
        set2 = set(name2_clean)
        
        if not set1 and not set2:
            return 1.0
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0.0
    
    def _get_similarity_reason(self, name1: str, name2: str) -> str:
        """Get reason for file similarity."""
        if name1.split('.')[0] == name2.split('.')[0]:
            return "Same base name"
        elif any(word in name1.lower() and word in name2.lower() for word in name1.split() if len(word) > 3):
            return "Shared keywords"
        else:
            return "Character similarity"
    
    def _find_version_files(self, base: str, directory: Path) -> List[Dict[str, Any]]:
        """Find version files in directory."""
        versions = []
        try:
            for file_path in directory.iterdir():
                if file_path.is_file() and base in file_path.name.lower():
                    versions.append({
                        'path': str(file_path),
                        'name': file_path.name,
                        'modified': file_path.stat().st_mtime if file_path.exists() else 0
                    })
        except:
            pass
        
        return sorted(versions, key=lambda x: x['modified'], reverse=True)
    
    def _find_companion_files(self, base_name: str, directory: Path, exclude_ext: str) -> List[str]:
        """Find companion files with same base name."""
        companions = []
        try:
            for file_path in directory.iterdir():
                if (file_path.is_file() and 
                    file_path.stem == base_name and 
                    file_path.suffix.lower() != exclude_ext):
                    companions.append(str(file_path))
        except:
            pass
        
        return companions
    
    def _calculate_reference_score(self, relationships: Dict[str, Any]) -> float:
        """Calculate how referenced/important a file seems."""
        score = 0.0
        
        # More similar files = higher score
        score += len(relationships['similar_files']) * 0.3
        
        # Version files indicate importance
        score += len(relationships['version_files']) * 0.2
        
        # Companion files indicate it's part of a project
        score += len(relationships['companion_files']) * 0.1
        
        return min(score, 1.0)  # Cap at 1.0
    
    def _analyze_peak_activity_hours(self) -> List[int]:
        """Analyze peak activity hours."""
        # Mock implementation - would analyze actual file access patterns
        return [9, 10, 14, 15, 16]  # Common work hours
    
    def _analyze_file_type_patterns(self) -> Dict[str, float]:
        """Analyze file type usage patterns."""
        # Mock implementation
        return {
            'document': 0.4,
            'image': 0.3,
            'code': 0.2,
            'other': 0.1
        }
    
    def _analyze_project_focus(self) -> List[str]:
        """Analyze current project focus."""
        # Mock implementation
        return ['development', 'documentation', 'research']
    
    def _calculate_efficiency_score(self) -> float:
        """Calculate user efficiency score."""
        # Mock implementation - would analyze search patterns, file access, etc.
        return 0.85
    
    def _get_productivity_suggestions(self) -> List[str]:
        """Get productivity suggestions."""
        return [
            "Consider organizing files by project",
            "Use tags for better file categorization", 
            "Set up automated backups during off-hours",
            "Archive old files to improve search performance"
        ]
    
    def _calculate_duplicate_probability(self, file1: Dict, file2: Dict) -> float:
        """Calculate probability that two files are duplicates."""
        score = 0.0
        
        # Same size is strong indicator
        if file1.get('size_bytes') == file2.get('size_bytes'):
            score += 0.5
        
        # Similar names
        name_similarity = self._calculate_file_similarity(
            file1.get('filename', ''), 
            file2.get('filename', '')
        )
        score += name_similarity * 0.3
        
        # Same file type
        if file1.get('file_type') == file2.get('file_type'):
            score += 0.2
        
        return min(score, 1.0)
    
    def _calculate_confidence_score(self, file1: Dict, file2: Dict) -> float:
        """Calculate confidence in duplicate detection."""
        # Higher confidence for exact size matches and high name similarity
        size_match = file1.get('size_bytes') == file2.get('size_bytes')
        name_sim = self._calculate_file_similarity(
            file1.get('filename', ''), 
            file2.get('filename', '')
        )
        
        if size_match and name_sim > 0.8:
            return 0.95
        elif size_match:
            return 0.7
        else:
            return 0.5
    
    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"