"""Advanced UI components for 36TB Intelligence."""

import streamlit as st
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
import json
from pathlib import Path

class UIComponents:
    """Advanced UI components with modern ergonomics."""
    
    @staticmethod
    def global_search_bar(placeholder: str = "🔍 Search across 36TB...", key: str = "global_search"):
        """Global search bar with keyboard shortcuts."""
        st.markdown("""
        <style>
        .global-search {
            position: sticky;
            top: 0;
            z-index: 999;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            padding: 1rem;
            margin: -1rem -1rem 1rem -1rem;
            border-radius: 0 0 10px 10px;
        }
        .search-container {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .search-input {
            flex-grow: 1;
            font-size: 16px !important;
            border-radius: 20px !important;
            border: none !important;
            padding: 12px 20px !important;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1) !important;
        }
        .search-shortcut {
            color: rgba(255,255,255,0.8);
            font-size: 12px;
            background: rgba(255,255,255,0.2);
            padding: 4px 8px;
            border-radius: 4px;
            margin-left: 10px;
        }
        </style>
        """, unsafe_allow_html=True)
        
        with st.container():
            st.markdown('<div class="global-search">', unsafe_allow_html=True)
            col1, col2 = st.columns([4, 1])
            with col1:
                search_query = st.text_input(
                    "",
                    placeholder=placeholder,
                    key=key,
                    label_visibility="collapsed"
                )
            with col2:
                st.markdown('<span class="search-shortcut">Ctrl+K</span>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        return search_query

    @staticmethod
    def quick_action_buttons(key_prefix: str = "main"):
        """Floating quick action buttons."""
        st.markdown("""
        <style>
        .quick-actions {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .quick-btn {
            width: 56px;
            height: 56px;
            border-radius: 50%;
            border: none;
            font-size: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }
        .quick-btn:hover {
            transform: scale(1.1);
            box-shadow: 0 6px 20px rgba(0,0,0,0.3);
        }
        .scan-btn { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
        .extract-btn { background: linear-gradient(135deg, #f093fb, #f5576c); color: white; }
        .sync-btn { background: linear-gradient(135deg, #4facfe, #00f2fe); color: white; }
        </style>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("🚀", help="Quick Scan", key=f"{key_prefix}_quick_scan"):
                return "scan"
        with col2:
            if st.button("🔄", help="Auto Extract", key=f"{key_prefix}_quick_extract"):
                return "extract"
        with col3:
            if st.button("☁️", help="Cloud Sync", key=f"{key_prefix}_quick_sync"):
                return "sync"
        return None

    @staticmethod
    def status_indicator(status: str, message: str = ""):
        """Modern status indicator."""
        status_colors = {
            "success": "#28a745",
            "warning": "#ffc107", 
            "error": "#dc3545",
            "info": "#17a2b8",
            "loading": "#6c757d"
        }
        
        color = status_colors.get(status, "#6c757d")
        st.markdown(f"""
        <div style="display: flex; align-items: center; padding: 8px 12px; background: {color}20; border-left: 4px solid {color}; border-radius: 4px; margin: 5px 0;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background: {color}; margin-right: 8px; {'animation: pulse 2s infinite;' if status == 'loading' else ''}"></div>
            <span style="color: {color}; font-weight: 500;">{message}</span>
        </div>
        """, unsafe_allow_html=True)

    @staticmethod
    def file_card(file_info: Dict[str, Any], show_preview: bool = True):
        """Modern file card component."""
        file_path = file_info.get('file_path', '')
        file_name = Path(file_path).name
        file_size = file_info.get('size_bytes', 0)
        file_type = file_info.get('file_type', 'unknown')
        modified = file_info.get('modified_at', '')
        
        # File type icons
        type_icons = {
            'pdf': '📄', 'doc': '📝', 'docx': '📝', 'txt': '📄',
            'jpg': '🖼️', 'png': '🖼️', 'gif': '🖼️', 'jpeg': '🖼️',
            'mp4': '🎥', 'avi': '🎥', 'mov': '🎥',
            'mp3': '🎵', 'wav': '🎵', 'flac': '🎵',
            'py': '🐍', 'js': '🟨', 'html': '🌐', 'css': '🎨',
            'zip': '📦', 'rar': '📦', '7z': '📦'
        }
        
        icon = type_icons.get(file_type.lower(), '📄')
        size_str = UIComponents.format_file_size(file_size)
        
        st.markdown(f"""<div style="border: 1px solid #e0e0e0; border-radius: 12px; padding: 16px; margin: 8px 0; background: white; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: all 0.3s ease; cursor: pointer;" onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 15px rgba(0,0,0,0.15)'" onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.1)'"><div style="display: flex; align-items: center; gap: 12px;"><div style="font-size: 32px;">{icon}</div><div style="flex-grow: 1;"><div style="font-weight: 600; color: #333; margin-bottom: 4px;">{file_name}</div><div style="font-size: 12px; color: #666;">{size_str} • {file_type.upper()} • {modified}</div><div style="font-size: 11px; color: #999; margin-top: 2px;">{file_path}</div></div></div></div>""", unsafe_allow_html=True)

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"

    @staticmethod
    def progress_toast(message: str, progress: float = 0):
        """Toast notification with progress."""
        st.toast(f"{message} ({progress:.0f}%)", icon="⏳")

    @staticmethod
    def breadcrumb_navigation(path_items: List[str]):
        """Breadcrumb navigation component."""
        if not path_items:
            return
            
        st.markdown("""
        <style>
        .breadcrumb {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 0;
            font-size: 14px;
            color: #666;
        }
        .breadcrumb-item {
            color: #007bff;
            text-decoration: none;
            cursor: pointer;
        }
        .breadcrumb-item:hover {
            text-decoration: underline;
        }
        .breadcrumb-separator {
            color: #ccc;
        }
        </style>
        """, unsafe_allow_html=True)
        
        breadcrumb_html = '<div class="breadcrumb">'
        for i, item in enumerate(path_items):
            if i > 0:
                breadcrumb_html += '<span class="breadcrumb-separator">></span>'
            if i == len(path_items) - 1:
                breadcrumb_html += f'<span style="color: #333; font-weight: 500;">{item}</span>'
            else:
                breadcrumb_html += f'<span class="breadcrumb-item">{item}</span>'
        breadcrumb_html += '</div>'
        
        st.markdown(breadcrumb_html, unsafe_allow_html=True)

    @staticmethod
    def filter_chips(filters: Dict[str, List[str]], active_filters: Dict[str, str]):
        """Visual filter chips."""
        st.markdown("""
        <style>
        .filter-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 16px 0;
        }
        .filter-chip {
            padding: 6px 12px;
            border-radius: 16px;
            border: 1px solid #ddd;
            background: white;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .filter-chip:hover {
            background: #f5f5f5;
        }
        .filter-chip.active {
            background: #007bff;
            color: white;
            border-color: #007bff;
        }
        </style>
        """, unsafe_allow_html=True)
        
        for filter_name, options in filters.items():
            st.write(f"**{filter_name}**")
            cols = st.columns(len(options))
            for i, option in enumerate(options):
                with cols[i]:
                    if st.button(option, key=f"filter_{filter_name}_{option}"):
                        active_filters[filter_name] = option
        
        return active_filters

    @staticmethod
    def theme_toggle():
        """Dark/Light mode toggle."""
        if 'dark_mode' not in st.session_state:
            st.session_state.dark_mode = False
        
        if st.button("🌓", help="Toggle Dark/Light Mode"):
            st.session_state.dark_mode = not st.session_state.dark_mode
        
        if st.session_state.dark_mode:
            st.markdown("""
            <style>
            .stApp {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            .stSidebar {
                background-color: #2d2d2d;
            }
            </style>
            """, unsafe_allow_html=True)

    @staticmethod
    def loading_spinner(message: str = "Loading..."):
        """Modern loading spinner."""
        st.markdown(f"""
        <div style="
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 40px;
            flex-direction: column;
            gap: 16px;
        ">
            <div style="
                width: 40px;
                height: 40px;
                border: 3px solid #f3f3f3;
                border-top: 3px solid #007bff;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            "></div>
            <div style="color: #666; font-weight: 500;">{message}</div>
        </div>
        
        <style>
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
            100% {{ opacity: 1; }}
        }}
        </style>
        """, unsafe_allow_html=True)

class WorkspaceManager:
    """Manage user workspaces and preferences."""
    
    def __init__(self):
        self.workspace_file = Path("data/workspace.json")
        self.workspace_file.parent.mkdir(exist_ok=True)
        
    def save_workspace(self, name: str, config: Dict[str, Any]):
        """Save workspace configuration."""
        workspaces = self.load_workspaces()
        workspaces[name] = {
            **config,
            'created_at': datetime.now().isoformat(),
            'last_used': datetime.now().isoformat()
        }
        
        with open(self.workspace_file, 'w') as f:
            json.dump(workspaces, f, indent=2)
    
    def load_workspaces(self) -> Dict[str, Any]:
        """Load all workspaces."""
        if not self.workspace_file.exists():
            return {}
        
        try:
            with open(self.workspace_file, 'r') as f:
                return json.load(f)
        except:
            return {}
    
    def delete_workspace(self, name: str):
        """Delete a workspace."""
        workspaces = self.load_workspaces()
        if name in workspaces:
            del workspaces[name]
            with open(self.workspace_file, 'w') as f:
                json.dump(workspaces, f, indent=2)

class SmartSuggestions:
    """Intelligent suggestions system."""
    
    @staticmethod
    def get_search_suggestions(query: str, history: List[str]) -> List[str]:
        """Get smart search suggestions."""
        suggestions = []
        
        # Recent searches
        for item in history[-5:]:
            if query.lower() in item.lower() and item not in suggestions:
                suggestions.append(item)
        
        # Common patterns
        if any(ext in query.lower() for ext in ['.pdf', '.doc', '.txt']):
            suggestions.append(f"type:document {query}")
        elif any(ext in query.lower() for ext in ['.jpg', '.png', '.gif']):
            suggestions.append(f"type:image {query}")
        
        return suggestions[:5]
    
    @staticmethod
    def get_file_insights(files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate insights from file collection."""
        if not files:
            return {}
        
        total_size = sum(f.get('size_bytes', 0) for f in files)
        file_types = {}
        
        for file in files:
            file_type = file.get('file_type', 'unknown')
            file_types[file_type] = file_types.get(file_type, 0) + 1
        
        return {
            'total_files': len(files),
            'total_size': total_size,
            'most_common_type': max(file_types, key=file_types.get) if file_types else 'none',
            'type_distribution': file_types
        }