"""Advanced search interface with modern UX."""

import streamlit as st
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
import json
from datetime import datetime, timedelta
import subprocess
import tempfile
import os

from src.ui.components import UIComponents, SmartSuggestions

class AdvancedSearchInterface:
    """Modern search interface with enhanced UX."""
    
    def __init__(self):
        self.components = UIComponents()
        self.suggestions = SmartSuggestions()
        self.selected_files: Set[str] = set()
        
    def render_search_interface(self):
        """Render the advanced search interface."""
        # Global search bar with real-time suggestions
        search_query = self._render_enhanced_search_bar()
        
        # Search filters and options
        filters = self._render_search_filters()
        
        # Search results with cards view
        if search_query or any(filters.values()):
            results = self._perform_search(search_query, filters)
            self._render_search_results(results)
        else:
            self._render_search_templates()
    
    def _render_enhanced_search_bar(self) -> str:
        """Enhanced search bar with autocomplete and suggestions."""
        st.markdown("""
        <style>
        .search-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 2rem;
            border-radius: 12px;
            margin-bottom: 2rem;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .search-input-wrapper {
            position: relative;
            margin-bottom: 1rem;
        }
        .search-suggestions {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            max-height: 200px;
            overflow-y: auto;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        .suggestion-item {
            padding: 12px 16px;
            cursor: pointer;
            border-bottom: 1px solid #f0f0f0;
            transition: background-color 0.2s;
        }
        .suggestion-item:hover {
            background-color: #f8f9fa;
        }
        .search-stats {
            color: rgba(255,255,255,0.9);
            font-size: 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        </style>
        """, unsafe_allow_html=True)
        
        with st.container():
            st.markdown('<div class="search-container">', unsafe_allow_html=True)
            
            # Main search input
            col1, col2 = st.columns([5, 1])
            with col1:
                search_query = st.text_input(
                    "",
                    placeholder="🔍 Search across your entire digital life...",
                    key="main_search",
                    label_visibility="collapsed"
                )
            with col2:
                search_mode = st.selectbox(
                    "",
                    ["🧠 Smart", "📝 Content", "📁 Files", "🏷️ Tags"],
                    key="search_mode",
                    label_visibility="collapsed"
                )
            
            # Search stats and suggestions
            if search_query:
                suggestions = self._get_search_suggestions(search_query)
                if suggestions:
                    st.markdown("💡 **Suggestions:**")
                    suggestion_cols = st.columns(min(len(suggestions), 3))
                    for i, suggestion in enumerate(suggestions[:3]):
                        with suggestion_cols[i]:
                            if st.button(f"💡 {suggestion}", key=f"suggestion_{i}"):
                                st.session_state.main_search = suggestion
                                st.rerun()
            
            # Search stats
            try:
                total_files = st.session_state.db.get_stats().get('total_files', 0)
                indexed_files = st.session_state.db.get_stats().get('indexed_files', 0)
                st.markdown(f"""
                <div class="search-stats">
                    <span>📁 {total_files:,} files indexed</span>
                    <span>🔍 {indexed_files:,} searchable</span>
                </div>
                """, unsafe_allow_html=True)
            except:
                pass
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        return search_query
    
    def _render_search_filters(self) -> Dict[str, Any]:
        """Render advanced search filters."""
        with st.expander("🎯 Advanced Filters", expanded=False):
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                file_types = st.multiselect(
                    "📄 File Types",
                    ["document", "image", "video", "audio", "archive", "code"],
                    key="filter_types"
                )
            
            with col2:
                size_range = st.select_slider(
                    "📊 File Size",
                    options=["Any", "< 1MB", "1-10MB", "10-100MB", "100MB-1GB", "> 1GB"],
                    value="Any",
                    key="filter_size"
                )
            
            with col3:
                date_range = st.selectbox(
                    "📅 Modified",
                    ["Any time", "Today", "This week", "This month", "This year", "Custom"],
                    key="filter_date"
                )
            
            with col4:
                location = st.text_input(
                    "📂 Location",
                    placeholder="Path contains...",
                    key="filter_location"
                )
            
            # Advanced options
            col1, col2 = st.columns(2)
            with col1:
                include_content = st.checkbox("🔍 Search file contents", value=True)
                case_sensitive = st.checkbox("📝 Case sensitive")
            
            with col2:
                regex_mode = st.checkbox("🔧 Regular expressions")
                exclude_system = st.checkbox("🚫 Exclude system files", value=True)
        
        return {
            "file_types": file_types,
            "size_range": size_range,
            "date_range": date_range,
            "location": location,
            "include_content": include_content,
            "case_sensitive": case_sensitive,
            "regex_mode": regex_mode,
            "exclude_system": exclude_system
        }
    
    def _perform_search(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Perform advanced search with filters."""
        try:
            # Use appropriate search engine based on mode
            search_mode = st.session_state.get("search_mode", "🧠 Smart")
            
            if "Smart" in search_mode:
                # Semantic search
                results = st.session_state.semantic_search.semantic_search(query, limit=50)
            elif "Content" in search_mode:
                # Content-based search
                results = st.session_state.advanced_search.search_content(query, filters)
            else:
                # File-based search
                results = st.session_state.advanced_search.search_files(query, filters)
            
            return results[:20]  # Limit for UI performance
            
        except Exception as e:
            st.error(f"Search error: {e}")
            return []
    
    def _render_search_results(self, results: List[Dict[str, Any]]):
        """Render search results with modern cards."""
        if not results:
            st.info("🔍 No results found. Try adjusting your search terms or filters.")
            return
        
        # Results header with actions
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.subheader(f"📋 {len(results)} Results")
        with col2:
            view_mode = st.radio("View:", ["🔲 Cards", "📋 List"], horizontal=True)
        with col3:
            if st.button("📤 Export Results"):
                self._export_results(results)
        
        # Bulk actions for selected files
        if self.selected_files:
            self._render_bulk_actions()
        
        # Results display
        if "Cards" in view_mode:
            self._render_cards_view(results)
        else:
            self._render_list_view(results)
    
    def _render_cards_view(self, results: List[Dict[str, Any]]):
        """Render results in cards view."""
        # Create grid layout
        cols_per_row = 2
        for i in range(0, len(results), cols_per_row):
            cols = st.columns(cols_per_row)
            
            for j in range(cols_per_row):
                if i + j < len(results):
                    result = results[i + j]
                    with cols[j]:
                        self._render_file_card_enhanced(result)
    
    def _render_file_card_enhanced(self, file_info: Dict[str, Any]):
        """Render enhanced file card with actions."""
        file_path = file_info.get('file_path', '')
        file_name = Path(file_path).name
        file_size = file_info.get('size_bytes', 0)
        file_type = file_info.get('file_type', 'unknown')
        modified = file_info.get('modified_at', '')
        relevance = file_info.get('relevance', 0)
        
        # File type icons
        type_icons = {
            'pdf': '📄', 'doc': '📝', 'docx': '📝', 'txt': '📄',
            'jpg': '🖼️', 'png': '🖼️', 'gif': '🖼️', 'jpeg': '🖼️',
            'mp4': '🎥', 'avi': '🎥', 'mov': '🎥',
            'mp3': '🎵', 'wav': '🎵', 'flac': '🎵',
            'py': '🐍', 'js': '🟨', 'html': '🌐', 'css': '🎨'
        }
        
        icon = type_icons.get(file_type.lower(), '📄')
        size_str = self.components.format_file_size(file_size)
        
        # Card container
        card_id = f"card_{hash(file_path)}"
        is_selected = file_path in self.selected_files
        
        card_style = f"""
            border: {'2px solid #007bff' if is_selected else '1px solid #e0e0e0'};
            border-radius: 12px;
            padding: 16px;
            margin: 8px 0;
            background: {'#f8f9ff' if is_selected else 'white'};
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            cursor: pointer;
        """
        
        with st.container():
            # Selection checkbox
            col1, col2 = st.columns([1, 20])
            with col1:
                selected = st.checkbox("", value=is_selected, key=f"select_{card_id}")
                if selected != is_selected:
                    if selected:
                        self.selected_files.add(file_path)
                    else:
                        self.selected_files.discard(file_path)
            
            with col2:
                # File info
                st.markdown(f"""
                <div style="{card_style}">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <div style="font-size: 32px;">{icon}</div>
                        <div style="flex-grow: 1;">
                            <div style="font-weight: 600; color: #333; margin-bottom: 4px;">{file_name}</div>
                            <div style="font-size: 12px; color: #666;">
                                {size_str} • {file_type.upper()} • {modified}
                            </div>
                            <div style="font-size: 11px; color: #999; margin-top: 2px;">
                                {file_path}
                            </div>
                        </div>
                        <div style="font-size: 12px; color: #007bff;">
                            {relevance:.0%} match
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            # Action buttons
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("👁️", help="Preview", key=f"preview_{card_id}"):
                    self._show_file_preview(file_path)
            with col2:
                if st.button("📂", help="Open Folder", key=f"folder_{card_id}"):
                    self._open_file_location(file_path)
            with col3:
                if st.button("🔗", help="Copy Path", key=f"copy_{card_id}"):
                    st.code(file_path)
            with col4:
                if st.button("⭐", help="Add to Favorites", key=f"fav_{card_id}"):
                    self._add_to_favorites(file_path)
    
    def _render_list_view(self, results: List[Dict[str, Any]]):
        """Render results in list view."""
        # Convert to DataFrame for better display
        display_data = []
        for result in results:
            display_data.append({
                "📄": Path(result.get('file_path', '')).name,
                "📊": self.components.format_file_size(result.get('size_bytes', 0)),
                "📅": result.get('modified_at', ''),
                "🎯": f"{result.get('relevance', 0):.0%}",
                "📂": str(Path(result.get('file_path', '')).parent)
            })
        
        df = pd.DataFrame(display_data)
        
        # Interactive table with selection
        selected_indices = st.multiselect(
            "Select files:",
            options=list(range(len(results))),
            format_func=lambda x: display_data[x]["📄"]
        )
        
        # Update selected files
        self.selected_files = {results[i]['file_path'] for i in selected_indices}
        
        st.dataframe(df, use_container_width=True)
    
    def _render_bulk_actions(self):
        """Render bulk actions for selected files."""
        st.markdown(f"**{len(self.selected_files)} files selected**")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("📤 Export List", key="bulk_export"):
                self._export_file_list()
        
        with col2:
            if st.button("🏷️ Add Tags", key="bulk_tag"):
                self._bulk_add_tags()
        
        with col3:
            if st.button("⭐ Add to Favorites", key="bulk_fav"):
                self._bulk_add_favorites()
        
        with col4:
            if st.button("🗑️ Clear Selection", key="clear_selection"):
                self.selected_files.clear()
                st.rerun()
    
    def _render_search_templates(self):
        """Render search templates for quick access."""
        st.subheader("🎯 Quick Search Templates")
        
        templates = [
            {"name": "📄 Recent Documents", "query": "type:document modified:last_week", "icon": "📄"},
            {"name": "🖼️ Large Images", "query": "type:image size:>10MB", "icon": "🖼️"},
            {"name": "🐍 Python Code", "query": "extension:py", "icon": "🐍"},
            {"name": "📊 Spreadsheets", "query": "type:spreadsheet", "icon": "📊"},
            {"name": "🎵 Music Collection", "query": "type:audio", "icon": "🎵"},
            {"name": "📦 Archive Files", "query": "type:archive", "icon": "📦"},
            {"name": "📹 Video Files", "query": "type:video", "icon": "📹"},
            {"name": "🗂️ Empty Folders", "query": "empty:folders", "icon": "🗂️"}
        ]
        
        # Template cards
        cols = st.columns(4)
        for i, template in enumerate(templates):
            with cols[i % 4]:
                if st.button(
                    f"{template['icon']} {template['name']}", 
                    key=f"template_{i}",
                    use_container_width=True
                ):
                    st.session_state.main_search = template["query"]
                    st.rerun()
    
    def _get_search_suggestions(self, query: str) -> List[str]:
        """Get intelligent search suggestions."""
        history = st.session_state.get('search_history', [])
        return self.suggestions.get_search_suggestions(query, history)
    
    def _show_file_preview(self, file_path: str):
        """Show file preview in modal."""
        with st.expander(f"👁️ Preview: {Path(file_path).name}", expanded=True):
            try:
                file_ext = Path(file_path).suffix.lower()
                
                if file_ext in ['.txt', '.md', '.py', '.js', '.html', '.css']:
                    # Text file preview
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()[:2000]  # First 2000 chars
                    st.code(content, language=file_ext[1:] if file_ext[1:] in ['py', 'js', 'html', 'css'] else 'text')
                
                elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
                    # Image preview
                    st.image(file_path, caption=Path(file_path).name, use_column_width=True)
                
                elif file_ext == '.pdf':
                    st.info("📄 PDF preview - Use external viewer for full document")
                    if st.button("🔗 Open PDF"):
                        self._open_file(file_path)
                
                else:
                    st.info(f"Preview not available for {file_ext} files")
                    if st.button("🔗 Open File"):
                        self._open_file(file_path)
                        
            except Exception as e:
                st.error(f"Preview error: {e}")
    
    def _open_file_location(self, file_path: str):
        """Open file location in explorer."""
        try:
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', '/select,', file_path])
            elif os.name == 'posix':  # macOS/Linux
                subprocess.run(['open', '-R', file_path])
            st.success("📂 Folder opened!")
        except Exception as e:
            st.error(f"Could not open folder: {e}")
    
    def _open_file(self, file_path: str):
        """Open file with default application."""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(file_path)
            elif os.name == 'posix':  # macOS/Linux
                subprocess.run(['open', file_path])
            st.success("🔗 File opened!")
        except Exception as e:
            st.error(f"Could not open file: {e}")
    
    def _add_to_favorites(self, file_path: str):
        """Add file to favorites."""
        if 'favorites' not in st.session_state:
            st.session_state.favorites = set()
        
        st.session_state.favorites.add(file_path)
        st.success(f"⭐ Added to favorites!")
    
    def _export_results(self, results: List[Dict[str, Any]]):
        """Export search results."""
        # Convert to CSV
        df = pd.DataFrame(results)
        csv = df.to_csv(index=False)
        
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"search_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    def _export_file_list(self):
        """Export selected file list."""
        file_list = '\n'.join(self.selected_files)
        
        st.download_button(
            label="📥 Download File List",
            data=file_list,
            file_name=f"selected_files_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain"
        )
    
    def _bulk_add_tags(self):
        """Bulk add tags to selected files."""
        with st.form("bulk_tag_form"):
            tags = st.text_input("Tags (comma-separated):")
            if st.form_submit_button("Add Tags"):
                tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
                for file_path in self.selected_files:
                    # Add tags using tag manager
                    st.session_state.tag_manager.add_tags(file_path, tag_list)
                st.success(f"Added tags to {len(self.selected_files)} files!")
    
    def _bulk_add_favorites(self):
        """Bulk add files to favorites."""
        if 'favorites' not in st.session_state:
            st.session_state.favorites = set()
        
        st.session_state.favorites.update(self.selected_files)
        st.success(f"Added {len(self.selected_files)} files to favorites!")