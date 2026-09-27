"""Streamlit UI for 36TB Intelligence."""

import streamlit as st
import pandas as pd
from pathlib import Path
import os
import time
from datetime import datetime
import sys
import threading
import queue
import sqlite3
import json
from typing import Dict, Any, List, Optional

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.core.database import DatabaseManager
from src.core.launch_profile import (
    Capability,
    capabilities_for,
    current_profile,
)
from src.core.scan_service import ScanService
from src.scanner.fast_engine import FastScannerEngine
from src.scanner.models import FileType, Priority
from src.analytics.dashboard import AnalyticsDashboard
from src.search.advanced_search import AdvancedSearch
from src.tags.tag_manager import TagManager
from src.cloud.sync_manager import CloudSyncManager

# Heavy components (torch/sentence-transformers/plotly) are imported lazily by
# their accessors below so a LITE/SMART/FULL startup never pays for them.

# Import disk selection components
from src.ui.disk_selector import DiskSelector
from src.ui.scan_controls import ScanController
from src.ui.activity_monitor import render_activity_monitor
from src.ui.interactive_table import InteractiveTable
from src.utils.disk_utils import get_available_drives, get_recommended_drives

# Import real-time activity monitor
from src.ui.real_time_monitor import (
    render_floating_activity_indicator,
    render_sidebar_activity_monitor,
    render_full_activity_dashboard,
    start_activity,
    finish_activity,
    ActivityType,
    ActivityTracker,
    track_activity
)


# Page config
st.set_page_config(
    page_title="36TB Intelligence",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'db' not in st.session_state:
    st.session_state.db = DatabaseManager()
    # A previous process may have died mid-scan; never let that run reconcile.
    st.session_state.db.recover_stale_runs()
if 'scanner_type' not in st.session_state:
    st.session_state.scanner_type = "FastScannerEngine"
if 'scanner' not in st.session_state:
    from src.scanner.engine import ScannerEngine
    if st.session_state.scanner_type == "ScannerEngine":
        st.session_state.scanner = ScannerEngine()
    else:
        st.session_state.scanner = FastScannerEngine()
if 'scan_running' not in st.session_state:
    st.session_state.scan_running = False
if 'advanced_search' not in st.session_state:
    st.session_state.advanced_search = AdvancedSearch()
if 'tag_manager' not in st.session_state:
    st.session_state.tag_manager = TagManager()
if 'cloud_sync' not in st.session_state:
    st.session_state.cloud_sync = CloudSyncManager()
if 'disk_selector' not in st.session_state:
    st.session_state.disk_selector = DiskSelector()
if 'scan_controller' not in st.session_state:
    st.session_state.scan_controller = ScanController()
if 'scan_thread' not in st.session_state:
    st.session_state.scan_thread = None
if 'progress_queue' not in st.session_state:
    st.session_state.progress_queue = queue.Queue()


# ---------------------------------------------------------------------------
# Lazy, profile-dependent components (M012-B2)
# ---------------------------------------------------------------------------
# These are created on first *use* rather than at startup.  Constructing them
# eagerly pulled torch/sentence-transformers into every process (~1 GB RSS, ~3 s
# import) even for LITE, which must stay lightweight and offline-capable.

def get_semantic_search():
    """Return the semantic search engine, building it on first use."""
    if 'semantic_search' not in st.session_state:
        from src.intelligence.semantic_search import SemanticSearchEngine

        st.session_state.semantic_search = SemanticSearchEngine()
    return st.session_state.semantic_search


def get_chat_engine():
    """Return the chat engine, building it on first use."""
    if 'chat_engine' not in st.session_state:
        from src.intelligence.chat_engine import ChatEngine

        st.session_state.chat_engine = ChatEngine()
    return st.session_state.chat_engine


def get_advanced_ai():
    """Return the advanced AI helper, building it on first use."""
    if 'advanced_ai' not in st.session_state:
        from src.ai.advanced_ai import AdvancedAI

        st.session_state.advanced_ai = AdvancedAI()
    return st.session_state.advanced_ai


class _AIEngineStatus:
    """Cheap sidebar AI-online probe (never loads an embedding model)."""

    def is_available(self) -> bool:
        try:
            from src.ai.providers.service import get_ai_service

            info = get_ai_service().llm().model_info()
            return bool(info.provider and info.provider != "unavailable")
        except Exception:  # noqa: BLE001 - the indicator must never break the UI
            return False


# Capability-gated navigation.  Core pages (scan/search/viewer/tags/dashboard/
# statistics/settings) are exposed by every profile; advanced pages depend on
# the launch profile and can be toggled with PIS_FEATURE_<CAPABILITY>.
_NAVIGATION: list[tuple[str, Capability]] = [
    ("🚀 Scanner", Capability.SCAN),
    ("🔍 Search", Capability.SEARCH),
    ("🎯 Advanced Search", Capability.ADVANCED_SEARCH),
    ("🧬 Duplicates & Versions", Capability.DUPLICATES),
    ("🧠 AI Search", Capability.SEMANTIC_SEARCH),
    ("💬 AI Chat", Capability.AI_CHAT),
    ("🏷️ Tags & Favorites", Capability.TAGS),
    ("📊 Dashboard", Capability.DASHBOARD),
    ("📈 Statistics", Capability.STATISTICS),
    ("🌌 Visualizations", Capability.VISUALIZATIONS),
    ("👁️ File Viewer", Capability.VIEWER),
    ("🔄 Auto-Extract", Capability.AUTO_EXTRACT),
    ("🤖 Advanced AI", Capability.ADVANCED_AI),
    ("☁️ Cloud Sync", Capability.CLOUD_SYNC),
]


def _navigation_pages() -> list[str]:
    caps = capabilities_for(current_profile())
    return [label for label, capability in _NAVIGATION if capability in caps]


def main():
    """Main application."""
    
    # Add floating activity indicator
    render_floating_activity_indicator()
    
    # Track app startup
    startup_id = start_activity(ActivityType.STARTUP, "Loading 36TB Intelligence Classic Interface")
    
    # Header
    st.title("🔍 36TB Intelligence")
    st.markdown("**Personal Knowledge Operating System** - Search your entire digital life")

    profile = current_profile()
    st.caption(
        f"Launch profile: **{profile.value.upper()}** · "
        f"AI mode: {os.environ.get('PIS_AI_MODE', 'auto')} · "
        f"remote content: {os.environ.get('PIS_REMOTE_CONTENT_POLICY', 'never')}"
    )
    
    # Sidebar
    with st.sidebar:
        # New Real-time Activity Monitor
        render_sidebar_activity_monitor()
        
        st.markdown("---")
        
        # Original Activity Monitor (keep for compatibility). AI status uses a
        # cheap probe so the sidebar never constructs the chat engine.
        render_activity_monitor(
            st.session_state.db,
            st.session_state.scanner,
            _AIEngineStatus(),
            st.session_state.tag_manager
        )
        
        st.markdown("---")

        # Compact AI/profile status. Rendered "cheap" so it never loads a local
        # embedding model just to show backend state (M012-B2).
        try:
            from src.ui.ai_status import render_ai_status

            render_ai_status()
        except Exception as exc:  # noqa: BLE001 - status must never break the UI
            st.caption(f"AI status unavailable: {exc}")

        st.markdown("---")
        st.header("⚙️ Options")
        
        # UI Version selector
        st.markdown("---")
        ui_version = st.selectbox(
            "🎨 Interface Version",
            ["Version Classique", "Version Moderne"],
            key="ui_version_selector"
        )
        
        if ui_version == "Version Moderne":
            st.info("🚀 Pour basculer vers l'interface moderne:")
            # Get current port from URL or use default
            current_port = st.query_params.get("port", "8501")
            modern_url = f"http://localhost:{current_port}/modern_app"
            st.markdown(f"### [👉 Cliquez ici pour ouvrir la Version Moderne]({modern_url})")
            st.markdown("Ou lancez dans un nouveau terminal:")
            st.code("streamlit run src/ui/modern_app.py", language="bash")
        
        st.markdown("---")
        
        page = st.radio(
            "Navigation",
            _navigation_pages(),
        )
    
    # Check for redirect to statistics
    if st.session_state.get('redirect_to_stats', False):
        st.session_state.redirect_to_stats = False
        page = "📈 Statistics"
    
    # Complete startup
    finish_activity(startup_id, success=True, message="Classic interface ready")
    
    # Pages with activity tracking
    if page == "🔍 Search":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Search page"):
            search_page()
    elif page == "🎯 Advanced Search":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Advanced Search page"):
            advanced_search_page()
    elif page == "🧬 Duplicates & Versions":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Duplicates & Versions page"):
            from src.ui.dedup_page import render as render_dedup_page
            render_dedup_page()
    elif page == "🏷️ Tags & Favorites":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Tags & Favorites page"):
            tags_favorites_page()
    elif page == "🤖 Advanced AI":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Advanced AI page"):
            advanced_ai_page()
    elif page == "🧠 AI Search":
        with ActivityTracker(ActivityType.AI_CHAT, "Opening AI Search page"):
            ai_search_page()
    elif page == "💬 AI Chat":
        with ActivityTracker(ActivityType.AI_CHAT, "Opening AI Chat page"):
            ai_chat_page()
    elif page == "☁️ Cloud Sync":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Cloud Sync page"):
            cloud_sync_page()
    elif page == "📊 Dashboard":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Dashboard page"):
            dashboard_page()
    elif page == "🌌 Visualizations":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Visualizations page"):
            visualizations_page()
    elif page == "🚀 Scanner":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Scanner page"):
            scanner_page()
    elif page == "🔄 Auto-Extract":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Auto-Extract page"):
            auto_extract_page()
    elif page == "📈 Statistics":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening Statistics page"):
            statistics_page()
    elif page == "👁️ File Viewer":
        with ActivityTracker(ActivityType.UI_INTERACTION, "Opening File Viewer page"):
            file_viewer_page()


def search_page():
    """Search interface."""
    st.header("🔍 Search Files")
    
    # Search bar
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Search query",
            placeholder="Enter filename, content, or leave empty to browse...",
            help="Search in filenames and content"
        )
    with col2:
        search_button = st.button("🔍 Search", type="primary", use_container_width=True)
    
    # Filters
    with st.expander("🎯 Advanced Filters"):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            file_type = st.selectbox(
                "File Type",
                ["All"] + [t.value for t in FileType]
            )
        
        with col2:
            priority = st.selectbox(
                "Priority",
                ["All"] + [p.value for p in Priority]
            )
        
        with col3:
            extension = st.text_input("Extension", placeholder=".pdf")
        
        with col4:
            max_results = st.number_input("Max Results", 10, 1000, 100)
        
        col5, col6 = st.columns(2)
        with col5:
            min_size = st.number_input("Min Size (MB)", 0, 10000, 0)
        with col6:
            max_size = st.number_input("Max Size (MB) - 0 = No limit", 0, 10000, 0)
        include_missing = st.checkbox(
            "Show missing files (recovery)",
            value=False,
            help="Include files absent from a completed scan (state=MISSING)",
        )
    
    # Always show some results (browse mode)
    show_results = search_button or query or True  # Always show results
    
    # Search execution
    if show_results:
        with st.spinner("Searching..."):
            results = st.session_state.db.search_files(
                query=query if query else None,
                file_type=FileType(file_type) if file_type != "All" else None,
                priority=Priority(priority) if priority != "All" else None,
                extension=extension if extension else None,
                min_size=min_size * 1024 * 1024 if min_size > 0 else None,
                max_size=max_size * 1024 * 1024 if max_size > 0 else None,
                limit=max_results,
                include_missing=include_missing,
            )
        
        # Display results with interactive table
        if results:
            # Use the interactive table component
            interactive_table = InteractiveTable(key_prefix="search_results")
            selected_items = interactive_table.render(
                data=results,
                title="📄 Search Results",
                page_size=20,
                show_actions=True,
                show_export=True
            )
            
            # Handle selected items
            if selected_items:
                st.markdown("---")
                st.subheader("🎯 Bulk Actions")
                
                bulk_cols = st.columns(4)
                
                with bulk_cols[0]:
                    if st.button("📂 Open All Locations", use_container_width=True):
                        for item in selected_items:
                            try:
                                open_file_location(Path(item['path']))
                            except:
                                pass
                        st.success(f"Opened {len(selected_items)} file locations!")
                
                with bulk_cols[1]:
                    if st.button("❤️ Add All to Favorites", use_container_width=True):
                        added_count = 0
                        for item in selected_items:
                            if st.session_state.tag_manager.add_to_favorites(item['id']):
                                added_count += 1
                        st.success(f"Added {added_count} items to favorites!")
                
                with bulk_cols[2]:
                    if st.button("🏷️ Tag Selected", use_container_width=True):
                        st.session_state['show_bulk_tagging'] = True
                
                with bulk_cols[3]:
                    if st.button("📊 Analyze Selection", use_container_width=True):
                        # Show analysis of selected files
                        st.session_state['show_selection_analysis'] = True
                
                # Bulk tagging modal
                if st.session_state.get('show_bulk_tagging', False):
                    with st.form("bulk_tagging"):
                        st.markdown("### 🏷️ Tag Selected Files")
                        
                        # Available tags
                        existing_tags = st.session_state.tag_manager.get_all_tags()
                        tag_names = [tag['name'] for tag in existing_tags]
                        
                        selected_tags = st.multiselect(
                            "Select existing tags",
                            tag_names
                        )
                        
                        new_tag = st.text_input("Or create new tag")
                        
                        tag_cols = st.columns(2)
                        with tag_cols[0]:
                            if st.form_submit_button("Apply Tags", type="primary"):
                                tags_to_apply = selected_tags.copy()
                                if new_tag:
                                    tags_to_apply.append(new_tag)
                                
                                tagged_count = 0
                                for item in selected_items:
                                    for tag in tags_to_apply:
                                        if st.session_state.tag_manager.tag_file(item['id'], tag):
                                            tagged_count += 1
                                
                                st.success(f"Applied tags to {len(selected_items)} files!")
                                st.session_state['show_bulk_tagging'] = False
                                st.rerun()
                        
                        with tag_cols[1]:
                            if st.form_submit_button("Cancel"):
                                st.session_state['show_bulk_tagging'] = False
                                st.rerun()
        else:
            st.info("No results found")


def advanced_search_page():
    """Advanced search with multiple filters."""
    st.header("🎯 Advanced Search")
    st.markdown("*Search with powerful filters and options*")
    
    # Main search query
    query = st.text_input(
        "Search Query",
        placeholder="Enter keywords to search in filenames and content...",
        help="Search across filenames, content, and file paths"
    )
    
    # Advanced filters in columns
    st.subheader("🔧 Filters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📁 File Filters**")
        
        # File types
        file_types = st.multiselect(
            "File Types",
            ["document", "image", "video", "audio", "text", "code", "archive", "other"],
            help="Filter by file type categories"
        )
        
        # Extensions
        extensions = st.text_input(
            "Extensions",
            placeholder="e.g., .pdf, .docx, .txt",
            help="Comma-separated list of extensions"
        )
        
        # Path contains
        path_contains = st.text_input(
            "Path Contains",
            placeholder="Filter by folder/path",
            help="Files whose path contains this text"
        )
        
        # Content filter
        has_content = st.selectbox(
            "Content Status",
            ["All Files", "Has Extracted Content", "No Content"],
            help="Filter by content extraction status"
        )
    
    with col2:
        st.markdown("**📏 Size & Date Filters**")
        
        # Size range
        size_filter = st.checkbox("Filter by Size")
        if size_filter:
            size_col1, size_col2 = st.columns(2)
            with size_col1:
                size_min = st.number_input(
                    "Min Size (MB)", 
                    min_value=0.0, 
                    value=0.0, 
                    step=0.1,
                    format="%.1f"
                )
            with size_col2:
                size_max = st.number_input(
                    "Max Size (MB)", 
                    min_value=0.0, 
                    value=1000.0, 
                    step=1.0,
                    format="%.1f"
                )
        
        # Date range
        date_filter = st.checkbox("Filter by Date")
        if date_filter:
            date_col1, date_col2 = st.columns(2)
            with date_col1:
                date_from = st.date_input("From Date")
            with date_col2:
                date_to = st.date_input("To Date")
    
    # Advanced options
    with st.expander("⚙️ Search Options"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            sort_by = st.selectbox(
                "Sort By",
                ["relevance", "name", "size", "date"],
                help="How to sort search results"
            )
        
        with col2:
            limit = st.number_input(
                "Max Results",
                min_value=10,
                max_value=1000,
                value=50,
                step=10
            )
        
        with col3:
            page_size = st.number_input(
                "Results per Page",
                min_value=10,
                max_value=100,
                value=20,
                step=10
            )
        
        # Regex pattern
        regex_pattern = st.text_input(
            "Regex Pattern (Advanced)",
            placeholder="e.g., .*report.*\\.pdf$",
            help="Regular expression to match filenames"
        )
    
    # Search button
    search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)
    
    # Execute search
    if search_clicked:
        # Prepare search parameters
        search_params = {
            'query': query if query else None,
            'file_types': file_types if file_types else None,
            'extensions': [ext.strip() for ext in extensions.split(',')] if extensions else None,
            'path_contains': path_contains if path_contains else None,
            'regex_pattern': regex_pattern if regex_pattern else None,
            'sort_by': sort_by,
            'limit': limit
        }
        
        # Size filters
        if size_filter:
            search_params['size_min'] = int(size_min * 1024 * 1024) if size_min > 0 else None
            search_params['size_max'] = int(size_max * 1024 * 1024) if size_max > 0 else None
        
        # Date filters  
        if date_filter:
            search_params['date_from'] = datetime.combine(date_from, datetime.min.time()) if 'date_from' in locals() else None
            search_params['date_to'] = datetime.combine(date_to, datetime.max.time()) if 'date_to' in locals() else None
        
        # Content filter
        if has_content == "Has Extracted Content":
            search_params['has_content'] = True
        elif has_content == "No Content":
            search_params['has_content'] = False
        
        # Execute search
        with st.spinner("🔍 Searching with advanced filters..."):
            try:
                search_result = st.session_state.advanced_search.search(**search_params)
                
                if search_result['success']:
                    results = search_result['results']
                    total_count = search_result['total_count']
                    
                    # Display results summary
                    st.success(f"✅ Found {total_count} files matching your criteria")
                    
                    if search_result['query_info']['filters_applied'] > 0:
                        st.info(f"🎯 {search_result['query_info']['filters_applied']} filters applied")
                    
                    # Pagination
                    if total_count > page_size:
                        pages = (total_count + page_size - 1) // page_size
                        page = st.selectbox(f"Page (showing {len(results)} of {total_count})", range(1, pages + 1))
                        
                        if page > 1:
                            search_params['offset'] = (page - 1) * page_size
                            search_params['limit'] = page_size
                            
                            search_result = st.session_state.advanced_search.search(**search_params)
                            results = search_result['results']
                    
                    # Display results
                    if results:
                        for i, result in enumerate(results):
                            with st.container():
                                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                                
                                with col1:
                                    # File info with relevance score
                                    icon = get_file_icon(result.get('file_type', 'other'))
                                    st.markdown(f"{icon} **{result['filename']}**")
                                    st.caption(result['path'])
                                    
                                    # Show relevance score if available
                                    if 'relevance_score' in result and result['relevance_score'] > 0:
                                        st.caption(f"🎯 Relevance: {result['relevance_score']:.1f}")
                                    
                                    # Content preview
                                    if result.get('content_text'):
                                        preview = result['content_text'][:150].replace('\n', ' ')
                                        st.caption(f"📄 {preview}..." if len(preview) == 150 else f"📄 {preview}")
                                
                                with col2:
                                    # File size
                                    if result.get('size_bytes'):
                                        size_mb = result['size_bytes'] / (1024 * 1024)
                                        if size_mb < 1:
                                            st.caption(f"{result['size_bytes'] / 1024:.1f} KB")
                                        else:
                                            st.caption(f"{size_mb:.1f} MB")
                                
                                with col3:
                                    # Modified date
                                    if result.get('modified_at'):
                                        try:
                                            mod_date = datetime.fromisoformat(result['modified_at'].replace('Z', '+00:00'))
                                            st.caption(mod_date.strftime("%Y-%m-%d"))
                                        except:
                                            st.caption(result['modified_at'][:10])
                                
                                with col4:
                                    # Action buttons
                                    file_path = Path(result['path'])
                                    if file_path.exists():
                                        if st.button("📂", key=f"folder_{i}", help="Open folder"):
                                            open_file_location(file_path)
                                        if st.button("👁️", key=f"preview_{i}", help="Preview"):
                                            show_file_preview(result, i)
                                
                                st.divider()
                    
                    else:
                        st.info("No files match your search criteria. Try adjusting your filters.")
                
                else:
                    st.error(f"Search failed: {search_result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"Search error: {str(e)}")


def tags_favorites_page():
    """Tags and favorites management page."""
    st.header("🏷️ Tags & Favorites")
    
    # Tab selection
    tab1, tab2, tab3, tab4 = st.tabs(["🏷️ Manage Tags", "⭐ Favorites", "🔍 Search by Tags", "📊 Statistics"])
    
    with tab1:
        st.subheader("Tag Management")
        
        # Create new tag
        with st.expander("➕ Create New Tag"):
            col1, col2 = st.columns([2, 1])
            with col1:
                new_tag_name = st.text_input("Tag Name", placeholder="Enter tag name...")
            with col2:
                new_tag_color = st.color_picker("Color", "#007ACC")
            
            new_tag_desc = st.text_area("Description (optional)", placeholder="Tag description...")
            
            if st.button("Create Tag", type="primary"):
                if new_tag_name.strip():
                    tag_id = st.session_state.tag_manager.create_tag(
                        new_tag_name.strip(), new_tag_color, new_tag_desc
                    )
                    if tag_id:
                        st.success(f"Created tag '{new_tag_name}'!")
                        st.rerun()
                    else:
                        st.error("Tag already exists or creation failed!")
                else:
                    st.warning("Please enter a tag name!")
        
        # List existing tags
        st.subheader("Existing Tags")
        tags = st.session_state.tag_manager.get_tags()
        
        if tags:
            for tag in tags:
                with st.container():
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    
                    with col1:
                        # Tag display with color
                        st.markdown(f"""
                        <div style="display: inline-block; background-color: {tag['color']}; color: white; 
                                    padding: 2px 8px; border-radius: 12px; margin: 2px; font-size: 12px;">
                            {tag['name']}
                        </div>
                        """, unsafe_allow_html=True)
                        if tag['description']:
                            st.caption(tag['description'])
                    
                    with col2:
                        st.caption(f"Used: {tag['usage_count']} times")
                        st.caption(f"Files: {tag['file_count']}")
                    
                    with col3:
                        if st.button("📝", key=f"edit_{tag['id']}", help="Edit tag"):
                            st.session_state[f"editing_{tag['id']}"] = True
                    
                    with col4:
                        if st.button("🗑️", key=f"delete_{tag['id']}", help="Delete tag"):
                            if st.session_state.tag_manager.delete_tag(tag['id']):
                                st.success(f"Deleted tag '{tag['name']}'")
                                st.rerun()
                    
                    # Edit mode
                    if st.session_state.get(f"editing_{tag['id']}", False):
                        with st.form(f"edit_form_{tag['id']}"):
                            edit_name = st.text_input("Name", value=tag['name'])
                            edit_color = st.color_picker("Color", value=tag['color'])
                            edit_desc = st.text_area("Description", value=tag['description'])
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("Save"):
                                    if st.session_state.tag_manager.update_tag(
                                        tag['id'], edit_name, edit_color, edit_desc
                                    ):
                                        st.success("Tag updated!")
                                        st.session_state[f"editing_{tag['id']}"] = False
                                        st.rerun()
                            
                            with col2:
                                if st.form_submit_button("Cancel"):
                                    st.session_state[f"editing_{tag['id']}"] = False
                                    st.rerun()
                    
                    st.divider()
        else:
            st.info("No tags created yet. Create your first tag above!")
    
    with tab2:
        st.subheader("⭐ Favorite Files")
        
        favorites = st.session_state.tag_manager.get_favorites()
        
        if favorites:
            st.success(f"You have {len(favorites)} favorite files")
            
            for fav in favorites:
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    
                    with col1:
                        icon = get_file_icon(fav.get('file_type', 'other'))
                        st.markdown(f"{icon} **{fav['filename']}**")
                        st.caption(fav['path'])
                        
                        if fav.get('favorite_notes'):
                            st.caption(f"📝 {fav['favorite_notes']}")
                    
                    with col2:
                        if fav.get('size_bytes'):
                            size_mb = fav['size_bytes'] / (1024 * 1024)
                            st.caption(f"Size: {size_mb:.1f} MB" if size_mb > 1 else f"Size: {fav['size_bytes'] / 1024:.1f} KB")
                    
                    with col3:
                        # Tags for this file
                        file_tags = st.session_state.tag_manager.get_file_tags(fav['id'])
                        if file_tags:
                            for tag in file_tags[:2]:  # Show first 2 tags
                                st.markdown(f"""
                                <div style="display: inline-block; background-color: {tag['color']}; color: white; 
                                            padding: 1px 6px; border-radius: 8px; margin: 1px; font-size: 10px;">
                                    {tag['name']}
                                </div>
                                """, unsafe_allow_html=True)
                    
                    with col4:
                        # Action buttons
                        file_path = Path(fav['path'])
                        if file_path.exists():
                            if st.button("📂", key=f"fav_folder_{fav['id']}", help="Open folder"):
                                open_file_location(file_path)
                            if st.button("💔", key=f"unfav_{fav['id']}", help="Remove from favorites"):
                                if st.session_state.tag_manager.remove_from_favorites(fav['id']):
                                    st.success("Removed from favorites")
                                    st.rerun()
                    
                    st.divider()
        else:
            st.info("No favorite files yet. Mark files as favorites from the search results!")
    
    with tab3:
        st.subheader("🔍 Search by Tags")
        
        # Get all tags for selection
        all_tags = st.session_state.tag_manager.get_tags()
        tag_options = [tag['name'] for tag in all_tags]
        
        if tag_options:
            col1, col2 = st.columns([3, 1])
            
            with col1:
                selected_tags = st.multiselect(
                    "Select Tags",
                    tag_options,
                    help="Select one or more tags to find files"
                )
            
            with col2:
                match_mode = st.radio(
                    "Match Mode",
                    ["Any Tag", "All Tags"],
                    help="Any: files with at least one tag, All: files with all selected tags"
                )
            
            if st.button("🔍 Search by Tags", type="primary") and selected_tags:
                with st.spinner("Searching files by tags..."):
                    results = st.session_state.tag_manager.search_files_by_tags(
                        selected_tags, match_all=(match_mode == "All Tags")
                    )
                
                if results:
                    st.success(f"Found {len(results)} files with selected tags")
                    
                    for result in results:
                        with st.container():
                            col1, col2, col3 = st.columns([3, 1, 1])
                            
                            with col1:
                                icon = get_file_icon(result.get('file_type', 'other'))
                                st.markdown(f"{icon} **{result['filename']}**")
                                st.caption(result['path'])
                            
                            with col2:
                                # Show file tags
                                file_tags = st.session_state.tag_manager.get_file_tags(result['id'])
                                for tag in file_tags[:3]:
                                    st.markdown(f"""
                                    <div style="display: inline-block; background-color: {tag['color']}; color: white; 
                                                padding: 1px 6px; border-radius: 8px; margin: 1px; font-size: 10px;">
                                        {tag['name']}
                                    </div>
                                    """, unsafe_allow_html=True)
                            
                            with col3:
                                file_path = Path(result['path'])
                                if file_path.exists():
                                    if st.button("📂", key=f"tag_folder_{result['id']}", help="Open folder"):
                                        open_file_location(file_path)
                            
                            st.divider()
                else:
                    st.info("No files found with the selected tags.")
        else:
            st.info("Create some tags first to search by them!")
    
    with tab4:
        st.subheader("📊 Tags & Favorites Statistics")
        
        stats = st.session_state.tag_manager.get_stats()
        
        if stats:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Tags", stats['total_tags'])
            
            with col2:
                st.metric("Tagged Files", stats['tagged_files'])
            
            with col3:
                st.metric("Favorite Files", stats['total_favorites'])
            
            with col4:
                st.metric("Avg Tags/File", f"{stats['avg_tags_per_file']:.1f}")
            
            # Most used tag
            if stats['most_used_tag']:
                st.subheader("🏆 Most Popular Tag")
                most_used = stats['most_used_tag']
                st.info(f"**{most_used['name']}** - used {most_used['usage_count']} times")
            
            # Popular tags chart
            popular_tags = st.session_state.tag_manager.get_popular_tags(10)
            if popular_tags:
                st.subheader("📈 Popular Tags")
                
                tag_names = [tag['name'] for tag in popular_tags]
                usage_counts = [tag['usage_count'] for tag in popular_tags]
                
                chart_data = pd.DataFrame({
                    'Tag': tag_names,
                    'Usage Count': usage_counts
                })
                
                st.bar_chart(chart_data.set_index('Tag'))


def advanced_ai_page():
    """Advanced AI with document summaries and intelligent analysis."""
    st.header("🤖 Advanced AI")
    st.markdown("*Intelligent document analysis with summaries and Q&A*")
    
    # Check AI availability
    if not get_advanced_ai().is_ollama_available():
        st.error("""
        🚨 **Ollama not available**
        
        Make sure Ollama is running:
        ```bash
        ollama serve
        ```
        
        The Advanced AI features require a running Ollama instance with the llama3.2 model.
        """)
        return
    
    st.success("🤖 Advanced AI system ready!")
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📝 Document Summaries", "❓ AI Q&A", "📊 AI Statistics", "⚙️ Settings"])
    
    with tab1:
        st.subheader("📝 Document Summaries")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("**Generate AI summaries for your documents**")
            
            # Batch generate summaries
            with st.expander("🚀 Batch Generate Summaries"):
                batch_col1, batch_col2 = st.columns(2)
                
                with batch_col1:
                    batch_limit = st.number_input("Files to process", 1, 200, 20)
                    
                with batch_col2:
                    file_types = st.multiselect(
                        "File types",
                        ["document", "text", "other"],
                        default=["document", "text"]
                    )
                
                if st.button("🤖 Generate Batch Summaries", type="primary"):
                    with st.spinner("Generating AI summaries..."):
                        results = get_advanced_ai().batch_generate_summaries(
                            limit=batch_limit, 
                            file_types=file_types if file_types else None
                        )
                    
                    if results['processed'] > 0:
                        st.success(f"✅ Processed {results['processed']} files: {results['successful']} successful, {results['failed']} failed")
                        
                        if results['details']:
                            with st.expander("📋 Detailed Results"):
                                details_df = pd.DataFrame(results['details'])
                                st.dataframe(details_df)
                    else:
                        st.info("No files found that need summaries")
        
        with col2:
            # AI Stats preview
            ai_stats = get_advanced_ai().get_stats()
            st.metric("Total Summaries", ai_stats.get('total_summaries', 0))
            st.metric("Pending Files", ai_stats.get('files_without_summaries', 0))
            st.metric("Avg Confidence", f"{ai_stats.get('avg_summary_confidence', 0):.1f}")
        
        # Show recent summaries
        st.subheader("📋 Recent Summaries")
        
        try:
            conn = sqlite3.connect(get_advanced_ai().db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.summary_text, s.key_points, s.topics, s.sentiment, 
                       s.confidence_score, s.created_at, f.filename, f.file_type
                FROM summaries s
                JOIN files f ON s.file_id = f.id
                ORDER BY s.created_at DESC
                LIMIT 5
            """)
            
            summaries = cursor.fetchall()
            conn.close()
            
            if summaries:
                for summary in summaries:
                    with st.expander(f"📄 {summary['filename']} - {summary['file_type']}"):
                        st.markdown(f"**Summary:** {summary['summary_text']}")
                        
                        if summary['key_points']:
                            try:
                                key_points = json.loads(summary['key_points'])
                                st.markdown("**Key Points:**")
                                for point in key_points:
                                    st.markdown(f"• {point}")
                            except:
                                pass
                        
                        if summary['topics']:
                            try:
                                topics = json.loads(summary['topics'])
                                st.markdown(f"**Topics:** {', '.join(topics)}")
                            except:
                                pass
                        
                        st.caption(f"Sentiment: {summary['sentiment']} | Confidence: {summary['confidence_score']:.1f} | Generated: {summary['created_at']}")
            else:
                st.info("No summaries generated yet. Use batch generation above!")
                
        except Exception as e:
            st.error(f"Error loading summaries: {e}")
    
    with tab2:
        st.subheader("❓ AI Q&A System")
        
        # Question input
        question = st.text_area(
            "Ask a question about your documents",
            placeholder="e.g., What are the main topics in my financial documents? How many contracts mention payment terms?",
            height=100
        )
        
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.button("🤖 Ask AI", type="primary", disabled=not question.strip()):
                if question.strip():
                    with st.spinner("AI is analyzing your documents..."):
                        response = get_advanced_ai().ask_question(question.strip())
                    
                    if response['success']:
                        st.success("✅ Answer generated!")
                        
                        with st.container():
                            st.markdown("**🤖 AI Answer:**")
                            st.markdown(response['answer'])
                            
                            st.caption(f"📁 Based on {response['files_used']} document(s)")
                    else:
                        st.error(f"❌ {response.get('error', 'Unknown error')}")
        
        with col2:
            st.metric("Questions Asked", ai_stats.get('total_questions', 0))
        
        # Q&A History
        st.subheader("📜 Recent Questions")
        
        qa_history = get_advanced_ai().get_qa_history(10)
        
        if qa_history:
            for qa in qa_history:
                with st.expander(f"❓ {qa['question'][:80]}..."):
                    st.markdown(f"**Question:** {qa['question']}")
                    st.markdown(f"**Answer:** {qa['answer']}")
                    st.caption(f"Asked: {qa['created_at']}")
        else:
            st.info("No questions asked yet. Try asking something above!")
    
    with tab3:
        st.subheader("📊 AI System Statistics")
        
        if ai_stats:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("📄 Total Summaries", ai_stats.get('total_summaries', 0))
            
            with col2:
                st.metric("❓ Questions Asked", ai_stats.get('total_questions', 0))
            
            with col3:
                st.metric("📂 Files Pending", ai_stats.get('files_without_summaries', 0))
            
            with col4:
                st.metric("🎯 Avg Confidence", f"{ai_stats.get('avg_summary_confidence', 0):.1f}")
            
            # Top topics
            if ai_stats.get('top_topics'):
                st.subheader("🔥 Popular Topics")
                
                topics_data = []
                for topic, count in ai_stats['top_topics'].items():
                    topics_data.append({'Topic': topic, 'Count': count})
                
                if topics_data:
                    topics_df = pd.DataFrame(topics_data)
                    st.bar_chart(topics_df.set_index('Topic'))
            
            # System status
            st.subheader("⚙️ System Status")
            
            status_col1, status_col2 = st.columns(2)
            
            with status_col1:
                if ai_stats.get('ollama_available'):
                    st.success("✅ Ollama Connected")
                else:
                    st.error("❌ Ollama Disconnected")
            
            with status_col2:
                st.info(f"🤖 Model: {ai_stats.get('model_used', 'Unknown')}")
        
        else:
            st.warning("Unable to load AI statistics")
    
    with tab4:
        st.subheader("⚙️ AI Settings")
        
        st.markdown("**System Configuration**")
        
        # Model info
        if ai_stats.get('model_used'):
            st.info(f"🤖 Current Model: **{ai_stats['model_used']}**")
        
        if ai_stats.get('ollama_available'):
            st.success("✅ Ollama Status: **Connected**")
        else:
            st.error("❌ Ollama Status: **Disconnected**")
            st.markdown("""
            **To fix connection issues:**
            1. Make sure Ollama is installed and running
            2. Start Ollama: `ollama serve`
            3. Ensure the llama3.2 model is available: `ollama pull llama3.2`
            """)
        
        st.markdown("---")
        st.markdown("**💡 AI Tips:**")
        st.markdown("""
        - Generate summaries for documents to enable intelligent search
        - Use the Q&A system to ask questions about your entire document collection
        - Higher confidence scores indicate more reliable summaries
        - Regular summary generation keeps your AI knowledge up-to-date
        """)


def cloud_sync_page():
    """Cloud synchronization management page."""
    st.header("☁️ Cloud Synchronization")
    st.markdown("*Backup and sync your data across devices*")
    
    # Get sync status
    sync_status = st.session_state.cloud_sync.get_status()
    
    # Status overview
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if sync_status['configured']:
            st.success("✅ Configured")
        else:
            st.error("❌ Not Configured")
    
    with col2:
        if sync_status['enabled']:
            st.success(f"☁️ {sync_status['provider'].title()}")
        else:
            st.warning("⚠️ Disabled")
    
    with col3:
        if sync_status['last_sync']:
            try:
                last_sync = datetime.fromisoformat(sync_status['last_sync'])
                st.info(f"🕒 {last_sync.strftime('%Y-%m-%d %H:%M')}")
            except:
                st.info("🕒 Never")
        else:
            st.info("🕒 Never")
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["⚙️ Setup", "☁️ Sync", "📋 Backups", "📊 History"])
    
    with tab1:
        st.subheader("☁️ Cloud Setup")
        
        if not sync_status['configured']:
            st.markdown("**Configure Dropbox Sync**")
            st.markdown("""
            To enable cloud sync:
            1. Go to [Dropbox App Console](https://www.dropbox.com/developers/apps)
            2. Create a new app with "Scoped access" and "App folder" permissions
            3. Copy your access token below
            """)
            
            access_token = st.text_input(
                "Dropbox Access Token",
                type="password",
                help="Your Dropbox app access token"
            )
            
            if st.button("🔗 Configure Dropbox", type="primary"):
                if access_token:
                    with st.spinner("Connecting to Dropbox..."):
                        success = st.session_state.cloud_sync.configure_dropbox(access_token)
                    
                    if success:
                        st.success("✅ Dropbox configured successfully!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to configure Dropbox. Check your token.")
                else:
                    st.warning("Please enter your access token")
        
        else:
            # Show configuration
            st.success(f"✅ Connected to {sync_status['provider'].title()}")
            
            if sync_status.get('account_name'):
                st.info(f"👤 Account: {sync_status['account_name']} ({sync_status.get('account_email', '')})")
            
            st.info(f"💻 Device: {sync_status['device_name']} ({sync_status['device_id']})")
            
            # Settings
            st.subheader("⚙️ Sync Settings")
            
            with st.form("sync_settings"):
                auto_sync = st.checkbox("Enable Auto Sync", value=sync_status.get('auto_sync', False))
                sync_interval = st.number_input("Sync Interval (hours)", 1, 24, sync_status.get('sync_interval_hours', 6))
                backup_count = st.number_input("Backups to Keep", 1, 20, sync_status.get('backup_count', 5))
                
                st.markdown("**What to Sync:**")
                sync_summaries = st.checkbox("AI Summaries", value=sync_status.get('sync_summaries', True))
                sync_tags = st.checkbox("Tags & Favorites", value=sync_status.get('sync_tags', True))
                sync_settings_chk = st.checkbox("Settings", value=sync_status.get('sync_settings', True))
                
                if st.form_submit_button("💾 Save Settings"):
                    settings = {
                        'auto_sync': auto_sync,
                        'sync_interval_hours': sync_interval,
                        'backup_count': backup_count,
                        'sync_summaries': sync_summaries,
                        'sync_tags': sync_tags,
                        'sync_settings': sync_settings_chk
                    }
                    
                    if st.session_state.cloud_sync.update_settings(settings):
                        st.success("✅ Settings updated!")
                    else:
                        st.error("❌ Failed to update settings")
    
    with tab2:
        st.subheader("☁️ Sync Operations")
        
        if not sync_status['configured']:
            st.warning("Please configure cloud sync first!")
            return
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**📤 Backup to Cloud**")
            st.markdown("Upload your database and settings to cloud storage")
            
            if st.button("☁️ Backup Now", type="primary", disabled=sync_status['sync_running']):
                with st.spinner("Creating and uploading backup..."):
                    result = st.session_state.cloud_sync.sync_to_cloud()
                
                if result['success']:
                    st.success(f"✅ {result['message']}")
                    st.info(f"📦 Size: {result['size'] / 1024 / 1024:.1f} MB | Duration: {result['duration']:.1f}s")
                else:
                    st.error(f"❌ {result['error']}")
        
        with col2:
            st.markdown("**📥 Restore from Cloud**")
            st.markdown("Download and restore from cloud backup")
            
            # List available backups
            backups = st.session_state.cloud_sync.list_cloud_backups()
            
            if backups:
                backup_options = []
                for backup in backups:
                    size_mb = backup['size'] / 1024 / 1024
                    backup_options.append(f"{backup['timestamp']} ({size_mb:.1f} MB)")
                
                selected_backup_idx = st.selectbox("Select Backup", range(len(backup_options)), format_func=lambda x: backup_options[x])
                
                if st.button("📥 Restore", disabled=sync_status['sync_running']):
                    selected_backup = backups[selected_backup_idx]
                    
                    with st.spinner("Downloading and restoring backup..."):
                        result = st.session_state.cloud_sync.restore_from_cloud(selected_backup['filename'])
                    
                    if result['success']:
                        st.success(f"✅ {result['message']}")
                        if result.get('imported'):
                            st.info(f"📊 Imported: {result['imported']}")
                    else:
                        st.error(f"❌ {result['error']}")
            else:
                st.info("No cloud backups found")
    
    with tab3:
        st.subheader("📋 Cloud Backups")
        
        if sync_status['configured']:
            backups = st.session_state.cloud_sync.list_cloud_backups()
            
            if backups:
                st.success(f"Found {len(backups)} backup(s) in cloud storage")
                
                backup_data = []
                for backup in backups:
                    size_mb = backup['size'] / 1024 / 1024
                    backup_data.append({
                        'Timestamp': backup['timestamp'],
                        'Device ID': backup['device_id'],
                        'Size (MB)': f"{size_mb:.1f}",
                        'Modified': backup['modified'][:19] if backup['modified'] else 'Unknown'
                    })
                
                backup_df = pd.DataFrame(backup_data)
                st.dataframe(backup_df, width=800)
            else:
                st.info("No backups found in cloud storage")
        else:
            st.warning("Configure cloud sync to see backups")
    
    with tab4:
        st.subheader("📊 Sync History")
        
        sync_stats = st.session_state.cloud_sync.get_sync_stats()
        
        if sync_stats:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Syncs", sync_stats.get('total_syncs', 0))
            
            with col2:
                st.metric("Successful", sync_stats.get('successful_syncs', 0))
            
            with col3:
                st.metric("Files Synced", sync_stats.get('total_files_synced', 0))
            
            with col4:
                data_mb = sync_stats.get('total_data_synced', 0) / 1024 / 1024
                st.metric("Data Synced", f"{data_mb:.1f} MB")
            
            # Last sync info
            if sync_stats.get('last_sync'):
                last_info = sync_stats['last_sync']
                st.info(f"🕒 Last sync: {last_info['type']} ({last_info['status']}) on {last_info['date']}")
        
        # Detailed history
        history = st.session_state.cloud_sync.get_sync_history(15)
        
        if history:
            st.subheader("📜 Recent Operations")
            
            history_data = []
            for entry in history:
                history_data.append({
                    'Date': entry['created_at'][:19],
                    'Type': entry['sync_type'],
                    'Status': entry['status'],
                    'Files': entry['files_synced'],
                    'Size (MB)': f"{entry['data_size'] / 1024 / 1024:.1f}" if entry['data_size'] else "0",
                    'Duration': f"{entry['duration_seconds']:.1f}s",
                    'Error': entry['error_message'][:50] if entry['error_message'] else ""
                })
            
            history_df = pd.DataFrame(history_data)
            st.dataframe(history_df, width=1000)
        else:
            st.info("No sync history available")


def visualizations_page():
    """Revolutionary data visualizations page."""
    st.header("🌌 Revolutionary Visualizations")
    st.markdown("*Explore your data like never before with advanced interactive visualizations*")
    
    # Check if visualization libraries are available
    try:
        import plotly.graph_objects as go
        import plotly.express as px
        import networkx as nx
        viz_available = True
    except ImportError:
        viz_available = False
    
    if not viz_available:
        st.error("""
        🚨 **Visualization libraries not available**
        
        Install the required libraries:
        ```bash
        pip install plotly networkx
        ```
        
        These enable revolutionary 3D visualizations, network graphs, and interactive analytics!
        """)
        return
    
    # Visualization tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🗂️ File Types", "📈 Size Analysis", "🔗 Directory Tree"])
    
    db = DatabaseManager()
    
    with tab1:
        st.subheader("📊 Data Overview")
        
        # Get basic stats
        stats = db.get_stats()
        
        # Create metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Files", f"{stats.get('total_files', 0):,}")
        with col2:
            st.metric("Total Size", f"{stats.get('total_gb', 0):.1f} GB")
        with col3:
            st.metric("File Types", len(stats.get('by_type', {})))
        with col4:
            st.metric("Extensions", len(stats.get('top_extensions', [])))
    
    with tab2:
        st.subheader("🗂️ File Types Distribution")
        
        file_types = stats.get('by_type', {})
        if file_types:
            # Create pie chart
            fig = px.pie(
                values=list(file_types.values()),
                names=list(file_types.keys()),
                title="File Types Distribution"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No file type data available")
    
    with tab3:
        st.subheader("📈 File Size Analysis")
        
        # Get largest files
        largest_files = stats.get('largest_files', [])
        if largest_files:
            df = pd.DataFrame(largest_files)
            df['size_mb'] = df['size_mb'].round(2)
            
            # Bar chart of largest files
            fig = px.bar(
                df.head(10),
                x='size_mb',
                y='filename',
                orientation='h',
                title="Top 10 Largest Files (MB)",
                labels={'size_mb': 'Size (MB)', 'filename': 'File Name'}
            )
            fig.update_layout(height=500)
            st.plotly_chart(fig, use_container_width=True)
            
            # Data table
            st.dataframe(df[['filename', 'size_mb', 'path']], use_container_width=True)
        else:
            st.info("No file size data available")
    
    with tab4:
        st.subheader("🔗 Directory Analysis")
        
        # Get directory statistics
        try:
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            
            # Get top directories by file count
            cursor.execute("""
                SELECT parent_dir, COUNT(*) as file_count, SUM(size_bytes) as total_size
                FROM files
                WHERE parent_dir IS NOT NULL
                GROUP BY parent_dir
                ORDER BY file_count DESC
                LIMIT 20
            """)
            
            dir_data = cursor.fetchall()
            conn.close()
            
            if dir_data:
                df_dirs = pd.DataFrame(dir_data, columns=['Directory', 'File Count', 'Total Size (Bytes)'])
                df_dirs['Total Size (GB)'] = (df_dirs['Total Size (Bytes)'] / (1024**3)).round(2)
                
                # Bar chart
                fig = px.bar(
                    df_dirs.head(15),
                    x='File Count',
                    y='Directory',
                    orientation='h',
                    title="Top Directories by File Count",
                    color='Total Size (GB)',
                    color_continuous_scale='viridis'
                )
                fig.update_layout(height=600)
                st.plotly_chart(fig, use_container_width=True)
                
                # Data table
                st.dataframe(df_dirs, use_container_width=True)
            else:
                st.info("No directory data available")
                
        except Exception as e:
            st.error(f"Error loading directory data: {e}")
    
    st.success("🌌 Advanced visualization system ready!")
    
    # Revolutionary visualizations with real advanced system
    st.markdown("---")
    st.subheader("🚀 Revolutionary 3D & Interactive Visualizations")
    
    # Controls
    col1, col2 = st.columns([3, 1])
    
    with col2:
        sample_size = st.slider("Sample Size", 100, 2000, 500, help="Files for 3D universe")
        max_nodes = st.slider("Network Nodes", 50, 200, 100, help="Network complexity")
    
    with col1:
        # Row 1: 3D Universe and Treemap
        viz_col1, viz_col2 = st.columns(2)
        
        with viz_col1:
            if st.button("🚀 3D File Universe", type="primary"):
                with st.spinner("Creating 3D galaxy..."):
                    from src.visualizations.advanced_viz import AdvancedVisualizations
                    advanced_viz = AdvancedVisualizations()
                    fig = advanced_viz.create_file_universe_3d(sample_size)
                    
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                    st.info("💡 Navigate in 3D - Your files as a galaxy!")
                else:
                    st.warning("No data available for 3D visualization")
        
        with viz_col2:
            if st.button("🗺️ Folder Treemap"):
                with st.spinner("Mapping territories..."):
                    from src.visualizations.advanced_viz import AdvancedVisualizations
                    advanced_viz = AdvancedVisualizations()
                    fig = advanced_viz.create_folder_treemap()
                
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                    st.info("💡 Click sections to explore!")
                else:
                    st.warning("No folder data available")
    
    # Row 2: Calendar and Sunburst
    viz_col3, viz_col4 = st.columns(2)
    
    with viz_col3:
        if st.button("📅 Activity Calendar"):
            with st.spinner("Creating calendar..."):
                from src.visualizations.advanced_viz import AdvancedVisualizations
                advanced_viz = AdvancedVisualizations()
                fig = advanced_viz.create_content_heatmap_calendar()
            
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.info("💡 Your productivity patterns!")
            else:
                st.warning("No activity data available")
    
    with viz_col4:
        if st.button("☀️ File Type Sunburst"):
            with st.spinner("Creating sunburst..."):
                from src.visualizations.advanced_viz import AdvancedVisualizations
                advanced_viz = AdvancedVisualizations()
                fig = advanced_viz.create_file_type_sunburst()
            
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.info("💡 Interactive hierarchy!")
            else:
                st.warning("No file type data available")
    
    # Row 3: Network and AI Radar
    viz_col5, viz_col6 = st.columns(2)
    
    with viz_col5:
        if st.button("🕸️ Document Network"):
            with st.spinner("Building network..."):
                from src.visualizations.advanced_viz import AdvancedVisualizations
                advanced_viz = AdvancedVisualizations()
                fig = advanced_viz.create_document_network_graph(max_nodes)
            
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.info("💡 Connected documents!")
            else:
                st.warning("No network data available")
    
    with viz_col6:
        if st.button("🧠 AI Intelligence Radar"):
            with st.spinner("AI analysis..."):
                from src.visualizations.advanced_viz import AdvancedVisualizations
                advanced_viz = AdvancedVisualizations()
                fig = advanced_viz.create_ai_insights_radar()
            
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.info("💡 System intelligence metrics!")
            else:
                st.warning("No AI data available")
    
    # Row 4: Advanced analytics
    viz_col7, viz_col8 = st.columns(2)
    
    with viz_col7:
        if st.button("🎻 Size Distribution"):
            with st.spinner("Creating violin plot..."):
                from src.visualizations.advanced_viz import AdvancedVisualizations
                advanced_viz = AdvancedVisualizations()
                fig = advanced_viz.create_size_distribution_violin()
            
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.info("💡 File size patterns!")
            else:
                st.warning("No size data available")
    
    with viz_col8:
        if st.button("🌊 Temporal Flow"):
            with st.spinner("Creating flow chart..."):
                from src.visualizations.advanced_viz import AdvancedVisualizations
                advanced_viz = AdvancedVisualizations()
                fig = advanced_viz.create_temporal_flow_chart()
            
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.info("💡 Time-based patterns!")
            else:
                st.warning("No temporal data available")


def ai_search_page():
    """AI-powered semantic search interface."""
    st.header("🧠 AI-Powered Search")
    
    # Check if semantic search is available
    if not get_semantic_search().is_available():
        st.error("""
        🚨 **Semantic search not available**
        
        Install the required library:
        ```bash
        pip install sentence-transformers
        ```
        
        This enables intelligent search that understands meaning, not just keywords!
        """)
        return
    
    st.success("🤖 AI search engine loaded and ready!")
    
    # Search interface
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "🧠 Ask your data anything",
            placeholder="e.g., 'documents about loans', 'contracts with clients', 'financial reports'...",
            help="AI understands meaning - try natural language!"
        )
    
    with col2:
        search_type = st.selectbox(
            "Search Mode",
            ["🧠 Semantic", "🔄 Hybrid", "👥 Similar Docs"]
        )
    
    # Advanced options
    with st.expander("🎯 AI Search Options"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            limit = st.number_input("Max Results", 5, 50, 20)
        
        with col2:
            similarity_threshold = st.slider(
                "Similarity Threshold", 
                0.0, 1.0, 0.3, 0.1,
                help="Higher = more similar results"
            )
        
        with col3:
            if search_type == "🔄 Hybrid":
                semantic_weight = st.slider("AI Weight", 0.0, 1.0, 0.7, 0.1)
    
    # Search button
    search_button = st.button("🚀 AI Search", type="primary", use_container_width=True)
    
    # Search execution
    if search_button and query:
        with st.spinner("🧠 AI is analyzing your request..."):
            try:
                if search_type == "🧠 Semantic":
                    results = get_semantic_search().semantic_search(
                        query, limit=limit, similarity_threshold=similarity_threshold
                    )
                elif search_type == "🔄 Hybrid":
                    results = get_semantic_search().hybrid_search(
                        query, limit=limit, semantic_weight=semantic_weight
                    )
                else:  # Similar docs - need a document ID
                    st.info("Select a document from regular search to find similar ones!")
                    return
                
            except Exception as e:
                st.error(f"Search error: {e}")
                return
        
        # Display results
        if results:
            st.success(f"🎯 Found {len(results)} intelligent matches")
            
            for i, result in enumerate(results):
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    
                    with col1:
                        # Filename with enhanced info
                        icon = get_file_icon(result['file_type'])
                        st.markdown(f"{icon} **{result['filename']}**")
                        st.caption(result['path'])
                        
                        # Show content preview for semantic results
                        if result.get('content_text') and len(result['content_text']) > 100:
                            preview = result['content_text'][:200] + "..."
                            st.markdown(f"*Preview:* {preview}")
                    
                    with col2:
                        size_mb = result['size_bytes'] / (1024 * 1024)
                        st.metric("Size", f"{size_mb:.2f} MB")
                    
                    with col3:
                        # Show AI similarity score
                        if 'semantic_similarity' in result:
                            similarity = result['semantic_similarity']
                            st.metric("🧠 AI Match", f"{similarity:.2f}")
                        elif 'combined_score' in result:
                            score = result['combined_score']
                            st.metric("🔄 Score", f"{score:.2f}")
                    
                    with col4:
                        if result['modified_at']:
                            modified = datetime.fromtimestamp(result['modified_at'].timestamp()) if hasattr(result['modified_at'], 'timestamp') else result['modified_at']
                            if isinstance(modified, str):
                                from datetime import datetime as dt
                                modified = dt.fromisoformat(modified.replace('Z', '+00:00'))
                            st.caption(modified.strftime("%Y-%m-%d"))
                    
                    # Similar documents button
                    if st.button(f"🔍 Find Similar", key=f"similar_{i}"):
                        with st.spinner("Finding similar documents..."):
                            similar_docs = get_semantic_search().find_similar_documents(
                                result['id'], limit=5
                            )
                            if similar_docs:
                                st.write("**Similar documents:**")
                                for sim_doc in similar_docs:
                                    st.write(f"- {sim_doc['filename']} (similarity: {sim_doc.get('semantic_similarity', 0):.2f})")
                            else:
                                st.info("No similar documents found")
                    
                    st.divider()
        else:
            st.info("No results found. Try adjusting your search terms or lowering the similarity threshold.")
    
    # Show AI search stats
    if st.checkbox("📊 Show AI Search Statistics"):
        stats = get_semantic_search().get_stats()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📄 Documents with AI", stats['documents_with_content'])
        with col2:
            st.metric("🧠 Cached Embeddings", stats['cached_embeddings'])  
        with col3:
            st.metric("🎯 Model Dimensions", stats.get('embedding_dimension', 0))
        
        st.json(stats)


def ai_chat_page():
    """Conversational AI interface for document interaction."""
    st.header("💬 AI Chat - Talk to Your Documents")
    
    # LLM Status Panel
    with st.expander("🤖 **LLM Connection Status**", expanded=True):
        try:
            import ollama
            
            # Get Ollama models
            models = ollama.list()
            available_models = [model.model for model in models.models]
            
            # Connection status
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("🟢 Ollama Status", "CONNECTED")
                st.caption("localhost:11434")
            
            with col2:
                st.metric("🤖 Active Model", "llama3.2:latest")
                if "llama3.2:latest" in available_models:
                    st.caption("✅ Model loaded and ready")
                else:
                    st.caption("❌ Model not found")
            
            with col3:
                embedding_available = len([m for m in available_models if "embed" in m]) > 0
                st.metric("🧠 Embeddings", "ACTIVE" if embedding_available else "INACTIVE")
                st.caption("nomic-embed-text:latest" if embedding_available else "Not available")
            
            # Model details
            st.markdown("---")
            st.markdown("**📋 Available Models:**")
            
            for model in models.models:
                model_name = model.model
                size_mb = model.size // (1024 * 1024)
                modified = model.modified_at.strftime("%Y-%m-%d %H:%M")
                
                # Model icon
                if "llama" in model_name.lower():
                    icon = "🦙"
                elif "embed" in model_name.lower():
                    icon = "🧠"
                else:
                    icon = "🤖"
                
                # Usage indicator
                if "llama3.2" in model_name:
                    usage = "🔥 **ACTIVE CHAT MODEL**"
                elif "embed" in model_name:
                    usage = "🔍 **SEARCH EMBEDDINGS**"
                else:
                    usage = "💤 Available"
                
                st.markdown(f"{icon} **{model_name}** ({size_mb} MB) - {usage}")
                st.caption(f"Last used: {modified}")
            
        except Exception as e:
            st.error(f"❌ **Ollama Connection Failed**: {str(e)}")
            st.markdown("""
            **Quick Fix:**
            ```bash
            # Start Ollama service
            ollama serve
            
            # Install required models
            ollama pull llama3.2
            ollama pull nomic-embed-text
            ```
            """)
            return
    
    # Check availability
    if not get_chat_engine().is_available():
        st.error("""
        🚨 **Conversational AI not available**
        
        Install Ollama and a compatible model:
        ```bash
        # Install Ollama
        curl -fsSL https://ollama.ai/install.sh | sh
        
        # Download a model
        ollama pull llama3.2:3b
        ```
        
        This enables natural conversations about your documents!
        """)
        return
    
    # Chat stats
    chat_stats = get_chat_engine().get_stats()
    st.success(f"🚀 AI Assistant ready! Using {chat_stats.get('model', 'Unknown model')}")
    
    # Chat interface
    st.subheader("💬 Conversation")
    
    # Clear conversation button
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("🗑️ Clear Chat"):
            get_chat_engine().clear_conversation()
            st.success("Conversation cleared!")
            st.rerun()
    
    with col2:
        search_context = st.checkbox("🔍 Search Context", True, help="Include relevant documents in conversation")
    
    # Chat history display
    history = get_chat_engine().get_conversation_history()
    
    if history:
        st.subheader("📝 Chat History")
        chat_container = st.container()
        
        with chat_container:
            for i, message in enumerate(history):
                if message['role'] == 'user':
                    st.chat_message("user").write(message['content'])
                else:
                    st.chat_message("assistant").write(message['content'])
    
    # User input
    st.subheader("✍️ Ask Your AI Assistant")
    
    # Predefined questions
    with st.expander("💡 Example Questions"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **Document Search:**
            - "Find documents about contracts"
            - "Show me financial reports from 2023"
            - "What files mention 'michel'?"
            """)
        
        with col2:
            st.markdown("""
            **Content Analysis:**
            - "Summarize my tax documents"
            - "What are the main topics in my files?"
            - "Find legal documents with deadlines"
            """)
        
        # Quick buttons for common queries
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📄 Find documents about 'michel'"):
                user_message = "Find documents that mention 'michel'"
        with col2:
            if st.button("💰 Show financial documents"):
                user_message = "Show me financial documents and reports"
        with col3:
            if st.button("📊 Summarize my collection"):
                user_message = "Give me a summary of my document collection"
    
    # Chat input
    user_message = st.text_area(
        "Your question:",
        placeholder="Ask anything about your documents... I can search, analyze, and explain!",
        height=100,
        key="chat_input"
    )
    
    # Send button
    send_button = st.button("💬 Send Message", type="primary", use_container_width=True)
    
    # Process chat message
    if send_button and user_message.strip():
        with st.spinner("🤖 AI is thinking..."):
            try:
                # Get AI response
                response_data = get_chat_engine().chat(
                    user_message, 
                    search_context=search_context
                )
                
                # Display response
                if 'error' not in response_data:
                    st.success("🤖 **AI Response:**")
                    st.write(response_data['response'])
                    
                    # Show sources if available
                    if response_data.get('sources'):
                        with st.expander(f"📚 Sources ({len(response_data['sources'])} documents)"):
                            for i, source in enumerate(response_data['sources']):
                                icon = get_file_icon(source.get('file_type', 'other'))
                                st.write(f"{icon} **{source.get('filename', 'Unknown')}**")
                                st.caption(f"Path: {source.get('path', 'Unknown')}")
                                
                                if source.get('content_text'):
                                    preview = source['content_text'][:150] + "..."
                                    st.markdown(f"*Preview:* {preview}")
                                
                                if 'semantic_similarity' in source:
                                    st.caption(f"Relevance: {source['semantic_similarity']:.3f}")
                                st.divider()
                    
                    # Response metadata
                    with st.expander("ℹ️ Response Details"):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("⏱️ Response Time", f"{response_data.get('response_time', 0):.2f}s")
                        with col2:
                            st.metric("🧠 Model", response_data.get('model', 'Unknown'))
                        with col3:
                            st.metric("📚 Context Used", "Yes" if response_data.get('context_used') else "No")
                
                else:
                    st.error(f"❌ Error: {response_data['error']}")
                
                # Clear input
                st.rerun()
                
            except Exception as e:
                st.error(f"💥 Chat error: {e}")
    
    # Document-specific chat
    st.subheader("🎯 Ask About Specific Document")
    
    # Get available documents
    with st.session_state.db.get_connection() as conn:
        cursor = conn.execute("""
            SELECT id, filename, path FROM files 
            WHERE content_extracted = 1 
            AND content_text IS NOT NULL 
            AND length(content_text) > 50
            ORDER BY filename
            LIMIT 100
        """)
        docs = cursor.fetchall()
    
    if docs:
        doc_options = {f"{doc[1]} ({doc[2]})": doc[0] for doc in docs}
        
        selected_doc_display = st.selectbox(
            "Select a document:",
            ["Choose a document..."] + list(doc_options.keys())
        )
        
        if selected_doc_display != "Choose a document...":
            selected_doc_id = doc_options[selected_doc_display]
            
            doc_question = st.text_input(
                "Question about this document:",
                placeholder="What is this document about? What are the key points?",
                key="doc_question"
            )
            
            if st.button("🎯 Ask About Document"):
                if doc_question.strip():
                    with st.spinner("🔍 Analyzing document..."):
                        try:
                            doc_response = get_chat_engine().ask_about_document(
                                selected_doc_id, 
                                doc_question
                            )
                            
                            if 'error' not in doc_response:
                                st.success("📄 **Document Analysis:**")
                                st.write(doc_response['response'])
                            else:
                                st.error(f"❌ Error: {doc_response['error']}")
                        
                        except Exception as e:
                            st.error(f"💥 Document analysis error: {e}")
                else:
                    st.warning("Please enter a question about the document.")
    else:
        st.info("📥 No documents with extracted content found. Run content extraction first!")
    
    # Document summarization
    st.subheader("📊 Document Collection Summary")
    
    col1, col2 = st.columns(2)
    with col1:
        file_type_filter = st.selectbox(
            "Summarize by file type:",
            ["all", "document", "image", "code", "email", "other"]
        )
    
    with col2:
        summary_limit = st.number_input("Max documents", 5, 50, 10)
    
    if st.button("📊 Generate Summary"):
        with st.spinner("🤖 Generating collection summary..."):
            try:
                summary_response = get_chat_engine().summarize_documents(
                    file_type=file_type_filter if file_type_filter != "all" else None,
                    limit=summary_limit
                )
                
                if 'error' not in summary_response:
                    st.success("📊 **Collection Summary:**")
                    st.write(summary_response['response'])
                    
                    if summary_response.get('sources'):
                        with st.expander(f"📚 Analyzed Documents ({len(summary_response['sources'])})"):
                            for source in summary_response['sources']:
                                icon = get_file_icon(source.get('file_type', 'other'))
                                st.write(f"{icon} {source.get('filename', 'Unknown')}")
                else:
                    st.error(f"❌ Error: {summary_response['error']}")
            
            except Exception as e:
                st.error(f"💥 Summary error: {e}")


def dashboard_page():
    """Advanced Analytics Dashboard for 36TB Intelligence."""
    st.header("📊 Analytics Dashboard")
    st.markdown("### Comprehensive insights into your file collection")
    
    # Initialize analytics
    analytics = AnalyticsDashboard()
    
    try:
        # Get comprehensive stats
        stats = analytics.get_overview_stats()
        
        # Key Performance Indicators
        st.subheader("🎯 Key Metrics")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="📁 Total Files", 
                value=f"{stats.total_files:,}",
                help="Total number of indexed files"
            )
        
        with col2:
            total_size_formatted = analytics.format_size(stats.total_size)
            st.metric(
                label="💾 Storage Used", 
                value=total_size_formatted,
                help="Total storage space used by all files"
            )
        
        with col3:
            searchable_count = len([f for f in stats.recent_files if f.get('content')])
            st.metric(
                label="🔍 Searchable Files", 
                value=f"{searchable_count:,}",
                help="Files with extracted content for semantic search"
            )
        
        with col4:
            avg_file_size = stats.total_size // max(stats.total_files, 1)
            st.metric(
                label="📏 Avg File Size", 
                value=analytics.format_size(avg_file_size),
                help="Average file size across collection"
            )
        
        # Charts Section
        st.subheader("📈 Visual Analytics")
        
        # File Types Distribution
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("#### 📊 File Types Distribution")
            if stats.by_type:
                # Create pie chart data
                type_data = list(stats.by_type.items())[:10]  # Top 10
                df_types = pd.DataFrame(type_data, columns=['File Type', 'Count'])
                
                # Bar chart
                st.bar_chart(df_types.set_index('File Type'))
                
                # Detailed table
                with st.expander("📋 Detailed Breakdown"):
                    type_dist = analytics.get_type_distribution(20)
                    df_detailed = pd.DataFrame([
                        {'Type': t, 'Files': c, 'Percentage': f"{p:.1f}%"}
                        for t, c, p in type_dist
                    ])
                    st.dataframe(df_detailed, width=600)
        
        with col2:
            st.markdown("#### 📏 Size Distribution")
            if stats.by_size_range:
                df_sizes = pd.DataFrame(
                    list(stats.by_size_range.items()),
                    columns=['Size Range', 'Count']
                )
                st.bar_chart(df_sizes.set_index('Size Range'))
        
        # Timeline and Insights
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 🕒 Recent Activity")
            timeline = analytics.get_timeline_stats(30)
            if timeline:
                df_timeline = pd.DataFrame([
                    {'Date': date, 'Files Modified': count}
                    for date, count in sorted(timeline.items())
                ])
                st.line_chart(df_timeline.set_index('Date'))
            else:
                st.info("No recent file modifications detected")
        
        with col2:
            st.markdown("#### 📁 Top Directories")
            dir_stats = analytics.get_directory_stats(10)
            if dir_stats:
                df_dirs = pd.DataFrame([
                    {
                        'Directory': d[:30] + '...' if len(d) > 30 else d,
                        'Files': c,
                        'Size': analytics.format_size(s)
                    }
                    for d, c, s in dir_stats[:8]
                ])
                st.dataframe(df_dirs, width=600)
        
        # File Insights
        st.subheader("🔍 File Insights")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 🏆 Largest Files")
            if stats.largest_files:
                for i, file_info in enumerate(stats.largest_files[:10], 1):
                    file_name = Path(file_info['name']).name
                    file_size = analytics.format_size(file_info['size'])
                    st.markdown(f"**{i}.** `{file_name}` - {file_size}")
        
        with col2:
            st.markdown("#### 🆕 Recently Modified")
            if stats.recent_files:
                for i, file_info in enumerate(stats.recent_files[:10], 1):
                    file_name = Path(file_info['name']).name
                    mod_date = file_info['modified'][:10] if file_info['modified'] else 'Unknown'
                    st.markdown(f"**{i}.** `{file_name}` - {mod_date}")
        
        # Search Optimization Insights
        st.subheader("🔍 Search Optimization")
        search_insights = analytics.get_search_insights()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            searchable = search_insights.get('searchable_files', 0)
            st.metric("✅ Searchable Files", f"{searchable:,}")
        
        with col2:
            non_searchable = search_insights.get('non_searchable_files', 0)
            st.metric("❌ Non-Searchable", f"{non_searchable:,}")
        
        with col3:
            extraction_opps = search_insights.get('extraction_opportunities', {})
            total_opps = sum(extraction_opps.values())
            st.metric("🔄 Extraction Potential", f"{total_opps:,}")
        
        if extraction_opps:
            st.markdown("#### 📈 Content Extraction Opportunities")
            df_opps = pd.DataFrame([
                {'File Type': ext, 'Count': count}
                for ext, count in extraction_opps.items()
            ])
            st.bar_chart(df_opps.set_index('File Type'))
        
        # Export Options
        st.subheader("💾 Export Analytics")
        col1, col2 = st.columns([1, 3])
        
        with col1:
            if st.button("📊 Export JSON Report"):
                export_path = analytics.export_stats()
                if export_path:
                    st.success(f"✅ Report exported to: `{export_path}`")
                else:
                    st.error("❌ Failed to export report")
        
        with col2:
            st.info("📋 Export includes all statistics, charts data, and insights in JSON format")
    
    except Exception as e:
        st.error(f"❌ Error loading analytics: {str(e)}")
        st.info("🔄 Try refreshing the page or ensure your database is accessible")


def background_scan_worker(paths, max_files, file_limit_mb, include_system, progress_queue):
    """Background worker function for scanning files."""
    try:
        # Import here to avoid issues with Streamlit session state in threads
        from src.scanner.fast_engine import FastScannerEngine
        from src.core.database import DatabaseManager
        from src.core.scan_service import ScanService
        from src.utils.disk_utils import validate_scan_path
        import time
        from datetime import datetime
        
        # Create new instances for the thread (can't share session state across threads)
        scanner = FastScannerEngine()
        db = DatabaseManager()
        service = ScanService(db)
        
        total_files_scanned = 0
        total_estimated_files = sum(validation['estimated_files'] for validation in 
                                   [validate_scan_path(path) for path in paths] 
                                   if validation.get('estimated_files', 0) > 0) or 1
        
        # Global progress callback that works across all paths
        def progress_callback(scan_progress):
            """Real-time progress callback for scanner engine."""
            try:
                fps = scan_progress.files_per_second if hasattr(scan_progress, 'files_per_second') else 0
                current_file = scan_progress.current_file if hasattr(scan_progress, 'current_file') else ''
                scanned_files = scan_progress.scanned_files if hasattr(scan_progress, 'scanned_files') else 0
                error_files = scan_progress.error_files if hasattr(scan_progress, 'error_files') else 0
                elapsed_seconds = scan_progress.elapsed_seconds if hasattr(scan_progress, 'elapsed_seconds') else 0
                start_time = scan_progress.start_time if hasattr(scan_progress, 'start_time') else datetime.now()
                
                current_total_files = total_files_scanned + scanned_files
                
                # Check if we've reached the file limit
                if max_files and current_total_files >= max_files:
                    status = 'completed'
                else:
                    status = 'running'
                
                # Calculate effective total (use max_files if we have a limit)
                effective_total = min(total_estimated_files, max_files) if max_files else total_estimated_files
                
                update_data = {
                    'status': status,
                    'progress': min(1.0, current_total_files / max(effective_total or 1, 1)),
                    'current_file': current_file or '',
                    'files_processed': current_total_files,
                    'total_files': effective_total,
                    'files_per_second': fps,
                    'start_time': start_time,
                    'current_path': current_path if 'current_path' in locals() else '',
                    'errors': error_files,
                    'elapsed_time': elapsed_seconds
                }
                
                # Force put with timeout to avoid blocking
                try:
                    progress_queue.put(update_data, timeout=0.1)
                except:
                    # If queue is full, clear it and try again
                    try:
                        while not progress_queue.empty():
                            progress_queue.get_nowait()
                        progress_queue.put(update_data, timeout=0.1)
                    except:
                        pass
                        
            except Exception as e:
                # Silent error handling in callback to prevent crash
                pass
        
        for path in paths:
            current_path = str(path)  # Make path available to callback
            files_per_drive = max_files
            file_size_limit = file_limit_mb * 1024 * 1024 if file_limit_mb > 0 else None
            
            # Scan files through the canonical lifecycle.
            session = service.session(path)
            try:
                files = list(scanner.scan_paths([Path(path)], limit=files_per_drive, progress_callback=progress_callback))

                # Apply file size filter
                filtered_files = []
                for file_info in files:
                    if file_size_limit and file_info.size_bytes > file_size_limit:
                        continue
                    filtered_files.append(file_info)

                if filtered_files:
                    session.record(filtered_files)
                    total_files_scanned += len(filtered_files)
                session.complete()
            except Exception as scan_error:
                session.fail(str(scan_error))
                raise
                
                # Check if we've reached the global file limit
                if max_files and total_files_scanned >= max_files:
                    # Send completion status and break
                    progress_queue.put({
                        'status': 'completed',
                        'progress': 1.0,
                        'files_processed': total_files_scanned,
                        'total_files': max_files,  # Use max_files as the effective total
                        'current_path': current_path,
                        'path_completed': True
                    })
                    break
                
                # Send update after each path is processed
                progress_queue.put({
                    'status': 'running',
                    'progress': min(1.0, total_files_scanned / max(total_estimated_files or 1, 1)),
                    'files_processed': total_files_scanned,
                    'total_files': total_estimated_files,
                    'current_path': current_path,
                    'path_completed': True
                })
        
        # Mark scan as completed
        progress_queue.put({
            'status': 'completed',
            'files_processed': total_files_scanned,
            'total_files': total_estimated_files,
            'progress': 1.0
        })
        
    except Exception as e:
        import traceback
        progress_queue.put({
            'status': 'error',
            'error': str(e),
            'traceback': traceback.format_exc()
        })

def scanner_page():
    """Advanced scanner control page with disk selection."""
    st.header("🚀 Advanced Scanner Control")
    
    # Disk selection interface
    disk_selector = st.session_state.disk_selector
    selected_paths = disk_selector.render_disk_selection(key_prefix="simple_scanner")
    
    if not selected_paths:
        st.warning("⚠️ Veuillez sélectionner des disques ou chemins à scanner.")
        return
    
    # Scan configuration
    st.markdown("### ⚙️ Configuration du Scan")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        max_files = st.number_input(
            "🔢 Fichiers max par disque:",
            min_value=0,
            max_value=1000000,
            value=100000,
            step=5000,
            help="Nombre maximum de fichiers à scanner par disque (0 = illimité)"
        )
    
    with col2:
        file_limit_mb = st.number_input(
            "📏 Taille max fichier (MB):",
            min_value=0,
            max_value=10000,
            value=500,
            help="Taille maximum des fichiers (0 = illimité)"
        )
    
    with col3:
        threads = st.selectbox(
            "⚡ Threads:",
            [1, 2, 4, 6, 8, 12],
            index=2,
            help="Nombre de threads pour le scan parallèle"
        )
    
    # Advanced scan controls
    st.markdown("---")
    scan_controller = st.session_state.scan_controller
    
    # Render scan controls with progress tracking
    scan_action = scan_controller.render_scan_controls(
        scanner_engine=st.session_state.scanner,
        key_prefix="simple_scanner"
    )
    
    # Handle scan control actions
    if scan_action == "pause":
        st.session_state.scanner.pause()
        scan_controller.set_status('paused')
        st.toast("⏸️ Scan mis en pause", icon="⏸️")
    
    elif scan_action == "resume":
        st.session_state.scanner.resume()
        scan_controller.set_status('running')
        st.toast("▶️ Scan repris", icon="▶️")
    
    elif scan_action == "stop":
        st.session_state.scanner.cancel()
        scan_controller.set_status('cancelled')
        st.session_state.scan_running = False
        st.toast("⏹️ Scan arrêté", icon="⏹️")
    
    elif scan_action == "reset":
        scan_controller.reset_progress()
        st.toast("🔄 Progression réinitialisée", icon="🔄")
    
    st.markdown("---")
    
    # Start scan button
    col1, col2 = st.columns([2, 1])
    
    with col1:
        scan_disabled = scan_controller.get_status() in ['running', 'paused']
        if st.button("🚀 Lancer le Scan Avancé", type="primary", use_container_width=True, disabled=scan_disabled):
            st.session_state.scan_running = True
            _start_advanced_scan_realtime(selected_paths, max_files, file_limit_mb, threads)
    
    with col2:
        if st.button("📊 Voir les Statistiques", use_container_width=True):
            # Navigate to statistics in the current app instead of switching pages
            st.session_state.redirect_to_stats = True
            st.rerun()


def _start_advanced_scan_realtime(paths, max_files, file_limit_mb, threads):
    """Start advanced scanning with real-time progress display using threading."""
    
    if not paths:
        st.error("❌ Aucun disque sélectionné !")
        return
    
    # Check if a scan is already running
    if st.session_state.scan_thread and st.session_state.scan_thread.is_alive():
        st.warning("⚠️ Un scan est déjà en cours !")
        return
    
    # Initialize scan controller
    scan_controller = st.session_state.scan_controller
    scan_controller.set_status('running')
    
    # Clear previous progress queue
    while not st.session_state.progress_queue.empty():
        try:
            st.session_state.progress_queue.get_nowait()
        except:
            break
    
    # Start background scan thread
    st.session_state.scan_thread = threading.Thread(
        target=background_scan_worker,
        args=(paths, max_files, file_limit_mb, False, st.session_state.progress_queue),
        daemon=True
    )
    st.session_state.scan_thread.start()
    
    # Show immediate feedback
    st.success("🚀 Scan démarré ! Les métriques se mettent à jour automatiquement toutes les secondes.")
    st.info("🔴 **LIVE** - Progression en temps réel activée !")
    
    # Force page refresh to show updated controls
    time.sleep(0.5)
    st.rerun()

def _start_advanced_scan(paths, max_files, file_limit_mb, threads):
    """Start advanced scanning with progress tracking."""
    
    # Get scan controller from session state
    scan_controller = st.session_state.scan_controller
    
    # Set scan controller to running state
    scan_controller.set_status('running')
    scan_controller.reset_progress()
    
    # Initialize progress tracking with scan controller
    total_files_scanned = 0
    total_estimated_files = max(len(paths) * max_files, 1)  # Rough estimate, ensure > 0
    
    # Update scan controller with initial data
    progress_data = {
        'status': 'running',
        'progress': 0.0,
        'current_file': '',
        'files_processed': 0,
        'total_files': total_estimated_files,
        'files_per_second': 0.0,
        'start_time': datetime.now(),
        'current_path': paths[0] if paths else '',
        'errors': 0
    }
    scan_controller.update_progress(progress_data)
    
    try:
        scanner = st.session_state.scanner
        st.session_state.scan_running = True
        
        for i, path in enumerate(paths):
            session = None
            # Update scan controller current path
            progress_data['current_path'] = str(path)
            scan_controller.update_progress(progress_data)
            
            # Calculate per-drive file limit
            files_per_drive = max_files
            file_size_limit = file_limit_mb * 1024 * 1024 if file_limit_mb > 0 else None
            
            try:
                start_time = time.time()
                
                # Update scan controller status
                progress_data['current_file'] = f"Scanning {path}..."
                scan_controller.update_progress(progress_data)
                
                # Use the advanced scanner with progress callback
                def progress_callback(scan_progress):
                    """Real-time progress callback for scanner engine."""
                    # Calculate files per second using scan_progress internal timing
                    fps = scan_progress.files_per_second
                    
                    # Update scan controller progress with real data
                    update_data = {
                        'status': 'running',
                        'progress': min(1.0, (total_files_scanned + scan_progress.scanned_files) / max(total_estimated_files or 1, 1)),
                        'current_file': scan_progress.current_file or '',
                        'files_processed': total_files_scanned + scan_progress.scanned_files,
                        'total_files': total_estimated_files,
                        'files_per_second': fps,
                        'start_time': scan_progress.start_time or datetime.now(),
                        'current_path': str(path),
                        'errors': scan_progress.error_files,
                        'elapsed_time': scan_progress.elapsed_seconds
                    }
                    scan_controller.update_progress(update_data)
                
                # Use scan_paths instead of fast_scan for better progress tracking
                session = ScanService(st.session_state.db).session(path)
                files = list(scanner.scan_paths([Path(path)], limit=files_per_drive, progress_callback=progress_callback))

                # Apply file size filter
                filtered_files = []
                for file_info in files:
                    if file_size_limit and file_info.size_bytes > file_size_limit:
                        continue
                    filtered_files.append(file_info)

                if filtered_files:
                    session.record(filtered_files)
                    total_files_scanned += len(filtered_files)
                    progress_data['files_processed'] = total_files_scanned
                    progress_data['progress'] = min(1.0, total_files_scanned / max(total_estimated_files or 1, 1))
                    scan_controller.update_progress(progress_data)
                session.complete()

            except Exception as e:
                # Update error count
                if session is not None:
                    session.fail(str(e))
                progress_data['errors'] = progress_data.get('errors', 0) + 1
                scan_controller.update_progress(progress_data)
                st.error(f"Erreur lors du scan de {path}: {str(e)}")
                continue
        
        # Update scan controller to completed status
        scan_controller.set_status('completed')
        progress_data['status'] = 'completed'
        progress_data['progress'] = 1.0
        progress_data['current_file'] = 'Scan terminé'
        scan_controller.update_progress(progress_data)
        
        st.session_state.scan_running = False
        
        if total_files_scanned > 0:
            st.success(f"""
            🎉 **Scan Multi-Disques Terminé !**
            
            - **📁 Disques scannés**: {len(paths)}
            - **📄 Fichiers indexés**: {total_files_scanned:,}
            - **⚡ Performance**: {threads} threads utilisés
            """)
        else:
            st.warning("⚠️ Scan terminé mais aucun nouveau fichier trouvé.")
        
    except Exception as e:
        # Update scan controller to error status
        scan_controller.set_status('cancelled')
        progress_data['status'] = 'cancelled'
        progress_data['current_file'] = f'Erreur: {str(e)}'
        scan_controller.update_progress(progress_data)
        st.session_state.scan_running = False
        st.error(f"❌ Échec du scan multi-disques: {e}")


def statistics_page():
    """Detailed statistics page."""
    st.header("📈 Statistics")
    
    stats = st.session_state.db.get_stats()
    
    # Summary
    st.subheader("📊 Database Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Files", f"{stats['total_files']:,}")
    with col2:
        st.metric("Total Size", f"{stats['total_gb']:.2f} GB")
    with col3:
        avg_size = (stats['total_bytes'] / stats['total_files'] / 1024 / 1024) if stats['total_files'] > 0 else 0
        st.metric("Average File Size", f"{avg_size:.2f} MB")
    
    # Detailed breakdown
    st.subheader("🗂️ File Type Breakdown")
    if stats['by_type']:
        df = pd.DataFrame([
            {'Type': k, 'Count': v, 'Percentage': f"{v/stats['total_files']*100:.1f}%"}
            for k, v in stats['by_type'].items()
        ])
        st.dataframe(df, use_container_width=True)
    
    st.subheader("🎯 Priority Breakdown")
    if stats['by_priority']:
        df = pd.DataFrame([
            {'Priority': k, 'Count': v, 'Percentage': f"{v/stats['total_files']*100:.1f}%"}
            for k, v in stats['by_priority'].items()
        ])
        st.dataframe(df, use_container_width=True)


def _render_archive_details(result: dict) -> None:
    """Archive-aware detail block for a search/result row (M009J.17)."""
    try:
        kind = result.get("document_kind")
        if kind == "ARCHIVE_MEMBER":
            st.caption("📦 Archive member")
            st.caption(f"Member path: {result.get('archive_member_path', '?')}")
            st.caption(f"Extraction: {result.get('extraction_state', '?')}")
            db = st.session_state.get("db")
            if db is not None:
                from src.archives.viewer import member_detail

                detail = member_detail(db, result.get("id"))
                if detail:
                    st.caption(f"Parent archive: {detail['parent_name']}")
                    if detail["preview"]:
                        st.text_area(
                            "Content preview (bounded)", detail["preview"],
                            height=140, key=f"arc_prev_{result.get('id')}",
                        )
        elif result.get("file_type") == "archive":
            db = st.session_state.get("db")
            if db is not None:
                from src.archives.viewer import container_summary

                summary = container_summary(db, result.get("id"))
                if summary:
                    st.caption(
                        f"📦 {summary['format']} · {summary['member_count']} members · "
                        f"{summary['compressed_human']} → {summary['expanded_human']} · "
                        f"status {summary['status']}"
                    )
    except Exception:  # noqa: BLE001 - viewer enrichment must never break the page
        pass


def file_viewer_page():
    """Dedicated file viewing and management page."""
    st.header("👁️ File Viewer & Content Explorer")
    
    # File browser section
    st.subheader("📁 Quick File Browser")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Path input
        browse_path = st.text_input(
            "📂 Browse Path", 
            value="C:\\", 
            help="Enter a path to browse files directly"
        )
    
    with col2:
        if st.button("🔍 Browse", type="primary"):
            if Path(browse_path).exists():
                st.session_state['browse_path'] = browse_path
                st.session_state['browse_results'] = list(Path(browse_path).glob("*"))[:100]
            else:
                st.error("Path not found")
    
    # Show browse results
    if hasattr(st.session_state, 'browse_results'):
        st.write(f"📁 **Contents of:** {st.session_state.get('browse_path', '')}")
        
        files = st.session_state.browse_results
        
        for i, file_path in enumerate(files):
            if file_path.is_file():
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                
                with col1:
                    icon = "📄" if file_path.suffix else "📁"
                    st.write(f"{icon} {file_path.name}")
                
                with col2:
                    if file_path.exists():
                        size = file_path.stat().st_size
                        st.caption(f"{size / (1024*1024):.2f} MB")
                
                with col3:
                    st.caption(file_path.suffix or "folder")
                
                with col4:
                    if st.button("👁️ View", key=f"browse_view_{i}"):
                        st.session_state['selected_file'] = str(file_path)
    
    st.markdown("---")
    
    # File search from database
    st.subheader("🔍 Search & View from Database")
    
    # Quick search
    search_term = st.text_input("Search files in database", placeholder="Enter filename or extension...")
    
    if search_term:
        with st.spinner("Searching database..."):
            results = st.session_state.db.search_files(
                query=search_term, 
                limit=20
            )
        
        if results:
            st.write(f"Found {len(results)} files in database:")
            
            for i, result in enumerate(results):
                with st.expander(f"📄 {result['filename']} ({result['size_bytes'] / (1024*1024):.2f} MB)"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Path:** {result['path']}")
                        st.write(f"**Type:** {result.get('file_type', 'unknown')}")
                        st.write(f"**Modified:** {result.get('modified_at', 'unknown')}")
                    
                    with col2:
                        if st.button(f"👁️ View This File", key=f"db_view_{i}"):
                            st.session_state['selected_file'] = result['path']
                            st.session_state['selected_file_data'] = result
                        
                        if st.button(f"📂 Open Location", key=f"db_location_{i}"):
                            from src.utils.os_open import reveal_path

                            if reveal_path(result["path"]):
                                st.success("Opening location...")
                            else:
                                st.error("Could not open file location")

                    _render_archive_details(result)
    
    st.markdown("---")
    
    # File viewer section
    if st.session_state.get('selected_file'):
        st.subheader("📄 File Content Viewer")
        
        selected_file = st.session_state['selected_file']
        selected_data = st.session_state.get('selected_file_data')
        
        # Create a mock result for the viewer
        if selected_data:
            show_file_preview(selected_data, 999)
        else:
            # Create basic file info for direct file browsing
            file_path = Path(selected_file)
            if file_path.exists():
                mock_result = {
                    'path': str(file_path),
                    'filename': file_path.name,
                    'size_bytes': file_path.stat().st_size,
                    'file_type': 'unknown',
                    'content_text': None,
                    'metadata': None
                }
                show_file_preview(mock_result, 999)
            else:
                st.error("Selected file not found")
        
        # Clear selection button
        if st.button("❌ Clear Selection"):
            if 'selected_file' in st.session_state:
                del st.session_state['selected_file']
            if 'selected_file_data' in st.session_state:
                del st.session_state['selected_file_data']
            st.rerun()
    else:
        st.info("👆 Select a file above to preview its content")
    
    # Batch operations section
    st.markdown("---")
    st.subheader("⚡ Batch Operations")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Refresh Database Stats"):
            stats = st.session_state.db.get_stats()
            st.write("📊 **Database Statistics:**")
            st.write(f"- Total files: {stats['total_files']:,}")
            st.write(f"- Total size: {stats['total_gb']:.2f} GB")
            st.write(f"- File types: {len(stats['by_type'])}")
    
    with col2:
        if st.button("🧹 Clear Preview Cache"):
            # Clear session state previews
            keys_to_clear = [key for key in st.session_state.keys() if 'preview' in key or 'selected' in key]
            for key in keys_to_clear:
                del st.session_state[key]
            st.success("Preview cache cleared")
    
    with col3:
        if st.button("📊 Show Large Files"):
            results = st.session_state.db.search_files(
                min_size=100 * 1024 * 1024,  # Files > 100MB
                limit=10
            )
            
            if results:
                st.write("📦 **Large Files (>100MB):**")
                for result in results:
                    size_mb = result['size_bytes'] / (1024 * 1024)
                    st.write(f"- {result['filename']} ({size_mb:.1f} MB)")
            else:
                st.info("No large files found")


def get_file_icon(file_type: str) -> str:
    """Get icon for file type."""
    icons = {
        'document': '📄',
        'image': '🖼️',
        'video': '🎬',
        'audio': '🎵',
        'archive': '📦',
        'email': '📧',
        'code': '💻',
        'other': '📎'
    }
    return icons.get(file_type, '📎')


def show_file_preview(result: dict, index: int) -> None:
    """Show file preview with content visualization."""
    file_path = Path(result['path'])
    
    # File info
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("📁 Full Path", "")
        st.code(str(file_path), language=None)
    
    with col2:
        st.metric("📊 File Info", "")
        st.write(f"**Type:** {result.get('file_type', 'unknown')}")
        st.write(f"**Extension:** {file_path.suffix}")
        size_mb = result['size_bytes'] / (1024 * 1024)
        st.write(f"**Size:** {size_mb:.2f} MB")
    
    with col3:
        st.metric("🔗 Actions", "")
        
        # Copy path button
        if st.button(f"📋 Copy Path", key=f"copy_{index}"):
            # JavaScript to copy to clipboard would go here
            st.success("Path copied to display above!")
        
        # Open file button (if it exists)
        if file_path.exists():
            if st.button(f"📂 Open File", key=f"open_{index}"):
                try:
                    from src.utils.os_open import open_path

                    if not open_path(file_path):
                        raise RuntimeError("no file opener available")
                    st.success("Opening file...")
                except Exception as e:
                    st.error(f"Could not open file: {e}")
        else:
            st.warning("File not found on disk")
    
    st.markdown("---")
    
    # Content preview
    st.subheader("📄 Content Preview")
    
    # Get extracted content if available
    content_text = result.get('content_text', '')
    
    if content_text:
        # Show content with syntax highlighting if possible
        file_ext = file_path.suffix.lower()
        
        # Determine language for syntax highlighting
        language = None
        if file_ext in ['.py']:
            language = 'python'
        elif file_ext in ['.js', '.json']:
            language = 'javascript'
        elif file_ext in ['.html', '.htm']:
            language = 'html'
        elif file_ext in ['.css']:
            language = 'css'
        elif file_ext in ['.sql']:
            language = 'sql'
        elif file_ext in ['.xml']:
            language = 'xml'
        elif file_ext in ['.md']:
            language = 'markdown'
        elif file_ext in ['.txt', '.log']:
            language = 'text'
        
        # Limit content length for display
        max_chars = 2000
        if len(content_text) > max_chars:
            preview_content = content_text[:max_chars] + f"\n\n... [Content truncated - showing first {max_chars} characters of {len(content_text)} total]"
        else:
            preview_content = content_text
        
        if language:
            st.code(preview_content, language=language, line_numbers=True)
        else:
            st.text_area("Content", preview_content, height=400, key=f"content_{index}")
        
        # Content stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Characters", f"{len(content_text):,}")
        with col2:
            words = len(content_text.split()) if content_text else 0
            st.metric("Words", f"{words:,}")
        with col3:
            lines = len(content_text.splitlines()) if content_text else 0
            st.metric("Lines", f"{lines:,}")
    
    else:
        # Try to read file directly for preview (with safety limits)
        if file_path.exists() and result['size_bytes'] < 10 * 1024 * 1024:  # Max 10MB for preview
            try:
                # Different handling based on file type
                if file_path.suffix.lower() in ['.txt', '.log', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.sql']:
                    # Text-based files
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(2000)  # Read first 2000 characters
                    
                    st.code(content, language='text', line_numbers=True)
                    
                    if len(content) == 2000:
                        st.caption("Preview truncated - showing first 2000 characters")
                
                elif file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                    # Image files
                    st.image(str(file_path), caption=f"Image: {file_path.name}", use_column_width=True)
                
                elif file_path.suffix.lower() == '.pdf':
                    # PDF files
                    st.info("📄 PDF file detected. Content extraction may be available in the database.")
                    
                    # Try to show first page or metadata
                    try:
                        import PyPDF2
                        with open(file_path, 'rb') as f:
                            reader = PyPDF2.PdfReader(f)
                            if len(reader.pages) > 0:
                                first_page = reader.pages[0].extract_text()
                                if first_page.strip():
                                    st.text_area("First page content", first_page[:1000], height=200)
                                st.info(f"PDF has {len(reader.pages)} pages")
                    except Exception as e:
                        st.warning(f"Could not extract PDF content: {e}")
                
                else:
                    # Other file types
                    st.info(f"📎 File type: {file_path.suffix}")
                    st.caption("Binary file - preview not available")
                    
                    # Show hex preview for small binary files
                    if result['size_bytes'] < 1024:  # Less than 1KB
                        with open(file_path, 'rb') as f:
                            hex_data = f.read(256).hex()
                        st.code(hex_data, language=None)
                        st.caption("Hex preview (first 256 bytes)")
            
            except Exception as e:
                st.error(f"Could not preview file: {e}")
        
        else:
            if not file_path.exists():
                st.warning("📂 File not found on disk - may have been moved or deleted")
            else:
                st.info(f"📦 File too large for preview ({result['size_bytes'] / (1024*1024):.1f} MB)")
            
            # Show basic file info instead
            st.write("**File Information:**")
            st.write(f"- Name: {file_path.name}")
            st.write(f"- Extension: {file_path.suffix}")
            st.write(f"- Size: {result['size_bytes']:,} bytes")
            st.write(f"- Type: {result.get('file_type', 'unknown')}")
    
    # Additional metadata if available
    if result.get('metadata'):
        with st.expander("🏷️ Additional Metadata", expanded=False):
            metadata = result['metadata']
            if isinstance(metadata, str):
                try:
                    import json
                    metadata = json.loads(metadata)
                except:
                    st.text(metadata)
            
            if isinstance(metadata, dict):
                for key, value in metadata.items():
                    st.write(f"**{key}:** {value}")
            else:
                st.json(metadata)


def auto_extract_page():
    """Auto-extraction interface for batch content extraction."""
    st.header("🔄 Auto Content Extraction")
    st.markdown("### Extract text content from documents for semantic search")
    
    # Initialize auto extractor (lazy import: extraction deps are optional)
    from src.extractors.auto_extractor import AutoExtractor

    auto_extractor = AutoExtractor()
    
    # Get candidates count
    candidates = auto_extractor.get_extraction_candidates()
    total_candidates = len(candidates)
    
    # Overview
    st.subheader("📊 Extraction Overview")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("📄 Files to Extract", f"{total_candidates:,}")
    
    with col2:
        estimation = auto_extractor.estimate_extraction_time(total_candidates)
        est_minutes = estimation['estimated_minutes']
        st.metric("⏱️ Est. Time", f"{est_minutes:.1f} min")
    
    with col3:
        st.metric("⚡ Max Workers", auto_extractor.max_workers)
    
    if total_candidates == 0:
        st.success("🎉 All files have been processed! No extraction needed.")
        return
    
    # File types breakdown
    st.subheader("📋 File Types to Process")
    
    if candidates:
        # Group by file type
        type_counts = {}
        total_size = 0
        
        for candidate in candidates:
            file_type = candidate.get('file_type', 'unknown')
            size = candidate.get('size_bytes', 0)
            
            if file_type not in type_counts:
                type_counts[file_type] = {'count': 0, 'size': 0}
            
            type_counts[file_type]['count'] += 1
            type_counts[file_type]['size'] += size
            total_size += size
        
        # Display breakdown
        col1, col2 = st.columns([2, 1])
        
        with col1:
            df_types = pd.DataFrame([
                {
                    'File Type': file_type, 
                    'Count': data['count'],
                    'Size': f"{data['size'] / (1024*1024):.1f} MB"
                }
                for file_type, data in sorted(type_counts.items(), key=lambda x: x[1]['count'], reverse=True)
            ])
            st.dataframe(df_types, width=500)
        
        with col2:
            analytics = AnalyticsDashboard()
            st.markdown("**Total Size:**")
            st.write(analytics.format_size(total_size))
    
    # Extraction options
    st.subheader("⚙️ Extraction Options")
    
    col1, col2 = st.columns(2)
    
    with col1:
        batch_size = st.selectbox(
            "Batch Size",
            [50, 100, 250, 500, 1000],
            index=1,
            help="Number of files to process in one batch"
        )
    
    with col2:
        extraction_type = st.selectbox(
            "Extraction Type",
            ["Priority Batch", "All Files"],
            help="Priority: PDFs and documents first. All: Process everything."
        )
    
    # Progress tracking
    if 'extraction_running' not in st.session_state:
        st.session_state.extraction_running = False
    
    if 'extraction_results' not in st.session_state:
        st.session_state.extraction_results = None
    
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("🚀 Start Extraction", disabled=st.session_state.extraction_running):
            st.session_state.extraction_running = True
            
            with st.spinner("Processing files..."):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def progress_callback(processed, total, results):
                    progress = processed / total
                    progress_bar.progress(progress)
                    status_text.text(f"Processed {processed}/{total} files ({results['successful']} successful)")
                
                try:
                    if extraction_type == "Priority Batch":
                        results = auto_extractor.extract_priority_batch(batch_size, progress_callback)
                    else:
                        results = auto_extractor.extract_all_candidates(progress_callback)
                    
                    st.session_state.extraction_results = results
                    st.session_state.extraction_running = False
                    
                    # Clear progress indicators
                    progress_bar.empty()
                    status_text.empty()
                    
                    # Show success
                    st.success(f"✅ Extraction completed! {results['successful']}/{results['processed']} files processed successfully.")
                    st.rerun()
                
                except Exception as e:
                    st.session_state.extraction_running = False
                    st.error(f"❌ Extraction failed: {str(e)}")
    
    with col2:
        if st.button("📊 Refresh Stats"):
            st.rerun()
    
    with col3:
        st.info("💡 Tip: Start with a small batch to test performance")
    
    # Show results
    if st.session_state.extraction_results:
        st.subheader("📈 Extraction Results")
        
        results = st.session_state.extraction_results
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("✅ Successful", results['successful'])
        
        with col2:
            st.metric("❌ Failed", results['failed'])
        
        with col3:
            st.metric("📊 Total Processed", results['processed'])
        
        with col4:
            success_rate = (results['successful'] / results['processed'] * 100) if results['processed'] > 0 else 0
            st.metric("🎯 Success Rate", f"{success_rate:.1f}%")
        
        # Detailed results
        if results.get('details'):
            with st.expander("📋 Detailed Results"):
                df_results = pd.DataFrame(results['details'])
                st.dataframe(df_results, width=800)
        
        # Clear results button
        if st.button("🗑️ Clear Results"):
            st.session_state.extraction_results = None
            st.rerun()
    
    # Statistics
    st.subheader("📊 Extraction Statistics")
    
    stats = auto_extractor.get_extraction_stats()
    
    if stats.get('extraction_manager'):
        manager_stats = stats['extraction_manager']
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Processed", manager_stats.get('total_processed', 0))
        
        with col2:
            st.metric("Success Rate", f"{manager_stats.get('success_rate', 0):.1f}%")
        
        with col3:
            st.metric("Avg Time/File", f"{manager_stats.get('avg_extraction_time', 0):.2f}s")
        
        # Per-extractor stats
        if manager_stats.get('by_extractor'):
            with st.expander("🔧 Per-Extractor Statistics"):
                extractor_data = []
                for name, data in manager_stats['by_extractor'].items():
                    extractor_data.append({
                        'Extractor': name,
                        'Processed': data['processed'],
                        'Successful': data['successful'],
                        'Failed': data['failed'],
                        'Success Rate': f"{(data['successful']/data['processed']*100):.1f}%" if data['processed'] > 0 else "0%",
                        'Total Time': f"{data['total_time']:.1f}s"
                    })
                
                if extractor_data:
                    df_extractors = pd.DataFrame(extractor_data)
                    st.dataframe(df_extractors, width=800)
    
    # Help section
    with st.expander("ℹ️ Help & Tips"):
        st.markdown("""
        **Auto Content Extraction** helps make your files searchable by extracting text content.
        
        **Supported Formats:**
        - 📄 **PDFs**: Text extraction from PDF documents
        - 📝 **Office**: Word (.docx), Excel (.xlsx), PowerPoint (.pptx)  
        - 📋 **Text**: Plain text, Markdown, code files
        - 📧 **Email**: .eml files
        - 🗂️ **Data**: JSON, XML, CSV files
        
        **Tips:**
        - Start with a small batch (50-100 files) to test performance
        - Priority batch processes PDFs and documents first
        - Extracted content enables semantic search with AI
        - Large files (>100MB) are automatically skipped
        
        **After extraction:**
        - Use 🧠 AI Search to find content semantically
        - Check 📊 Dashboard for updated statistics
        - Files are marked as processed to avoid re-extraction
        """)


def open_file_location(file_path: Path):
    """Reveal a file in the OS file manager (cross-platform)."""
    from src.utils.os_open import reveal_path

    if reveal_path(file_path):
        st.success("Opening folder...")
    else:
        st.error("Could not open folder")


def manage_file_tags(file_id: int, filename: str):
    """Inline tag management for a file."""
    # Get current tags for the file
    current_tags = st.session_state.tag_manager.get_file_tags(file_id)
    current_tag_names = [tag['name'] for tag in current_tags]
    
    # Display current tags
    if current_tags:
        st.markdown("**Current Tags:**")
        tags_html = ""
        for tag in current_tags:
            tags_html += f"""
            <div style="display: inline-block; background-color: {tag['color']}; color: white; 
                        padding: 3px 8px; border-radius: 12px; margin: 2px; font-size: 12px;">
                {tag['name']}
            </div>
            """
        st.markdown(tags_html, unsafe_allow_html=True)
        st.markdown("")
    
    # Get all available tags
    all_tags = st.session_state.tag_manager.get_tags()
    available_tag_names = [tag['name'] for tag in all_tags if tag['name'] not in current_tag_names]
    
    # Add tags section
    if available_tag_names:
        st.markdown("**Add Tags:**")
        selected_tags = st.multiselect(
            "Select tags to add",
            available_tag_names,
            key=f"add_tags_{file_id}",
            help="Select one or more tags to add to this file"
        )
        
        if st.button("➕ Add Selected Tags", key=f"add_tags_btn_{file_id}"):
            added_count = 0
            for tag_name in selected_tags:
                # Find tag ID
                tag_id = next((tag['id'] for tag in all_tags if tag['name'] == tag_name), None)
                if tag_id and st.session_state.tag_manager.add_tag_to_file(file_id, tag_id):
                    added_count += 1
            
            if added_count > 0:
                st.success(f"Added {added_count} tag(s)!")
                st.rerun()
    
    # Remove tags section
    if current_tags:
        st.markdown("**Remove Tags:**")
        tags_to_remove = st.multiselect(
            "Select tags to remove",
            current_tag_names,
            key=f"remove_tags_{file_id}",
            help="Select tags to remove from this file"
        )
        
        if st.button("➖ Remove Selected Tags", key=f"remove_tags_btn_{file_id}"):
            removed_count = 0
            for tag_name in tags_to_remove:
                # Find tag ID
                tag_id = next((tag['id'] for tag in current_tags if tag['name'] == tag_name), None)
                if tag_id and st.session_state.tag_manager.remove_tag_from_file(file_id, tag_id):
                    removed_count += 1
            
            if removed_count > 0:
                st.success(f"Removed {removed_count} tag(s)!")
                st.rerun()
    
    # Quick tag suggestions
    suggestions = st.session_state.tag_manager.suggest_tags_for_file(filename)
    if suggestions:
        st.markdown("**💡 Suggested Tags:**")
        suggestion_col1, suggestion_col2 = st.columns([3, 1])
        
        with suggestion_col1:
            selected_suggestions = st.multiselect(
                "AI-suggested tags for this file",
                [s for s in suggestions if s not in current_tag_names],
                key=f"suggestions_{file_id}",
                help="These tags are suggested based on the filename and content"
            )
        
        with suggestion_col2:
            if st.button("✨ Add Suggestions", key=f"add_suggestions_{file_id}"):
                added_count = 0
                for suggestion in selected_suggestions:
                    # Create tag if it doesn't exist
                    tag_id = st.session_state.tag_manager.create_tag(suggestion)
                    if not tag_id:
                        # Tag exists, find its ID
                        existing_tags = st.session_state.tag_manager.get_tags()
                        tag_id = next((tag['id'] for tag in existing_tags if tag['name'] == suggestion), None)
                    
                    if tag_id and st.session_state.tag_manager.add_tag_to_file(file_id, tag_id):
                        added_count += 1
                
                if added_count > 0:
                    st.success(f"Added {added_count} suggested tag(s)!")
                    st.rerun()


if __name__ == "__main__":
    main()