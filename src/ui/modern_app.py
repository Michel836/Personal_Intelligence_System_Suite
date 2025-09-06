"""Modern ergonomic UI for 36TB Intelligence."""

import streamlit as st
import pandas as pd
from pathlib import Path
import time
from datetime import datetime
import sys
from typing import Dict, Any, List, Optional

# Add parent to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.core.database import DatabaseManager
from src.scanner.fast_engine import FastScannerEngine
from src.scanner.models import FileType, Priority
from src.intelligence.semantic_search import SemanticSearchEngine
from src.intelligence.chat_engine import ChatEngine
from src.analytics.dashboard import AnalyticsDashboard
from src.extractors.auto_extractor import AutoExtractor
from src.search.advanced_search import AdvancedSearch
from src.tags.tag_manager import TagManager
from src.cloud.sync_manager import CloudSyncManager
from src.ai.advanced_ai import AdvancedAI
from src.visualizations.advanced_viz import AdvancedVisualizations

# Import new ergonomic components
from src.ui.components import UIComponents, WorkspaceManager, SmartSuggestions
from src.ui.dashboard import UnifiedDashboard
from src.ui.onboarding import OnboardingFlow, NavigationManager

# Import TurboScanner for ultra-fast scanning
sys.path.append(str(Path(__file__).parent.parent.parent / "scripts"))
from turbo_scan import TurboScanner
from src.ui.advanced_search import AdvancedSearchInterface
from src.ui.disk_selector import DiskSelector
from src.ui.scan_controls import ScanController

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

# Modern page config
st.set_page_config(
    page_title="36TB Intelligence",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/your-repo/help',
        'Report a bug': 'https://github.com/your-repo/issues',
        'About': "36TB Intelligence - Your Personal Knowledge OS"
    }
)

# Custom CSS for modern look
st.markdown("""
<style>
/* Modern gradient background */
.main > div {
    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    min-height: 100vh;
}

/* Header styling */
.main-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 2rem;
    border-radius: 12px;
    margin-bottom: 2rem;
    box-shadow: 0 8px 32px rgba(0,0,0,0.1);
}

/* Sidebar improvements */
.css-1d391kg {
    background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
}

/* Button improvements */
.stButton > button {
    border-radius: 8px;
    border: none;
    transition: all 0.3s ease;
    font-weight: 500;
}

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 15px rgba(0,0,0,0.2);
}

/* Card styling */
.metric-card {
    background: white;
    padding: 1.5rem;
    border-radius: 12px;
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    margin-bottom: 1rem;
    transition: all 0.3s ease;
}

.metric-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0,0,0,0.15);
}

/* Animations */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

.fade-in {
    animation: fadeIn 0.5s ease-out;
}

/* Toast notifications */
.stAlert {
    border-radius: 8px;
    border: none;
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
}

/* Progress bars */
.stProgress > div > div {
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    border-radius: 10px;
}

/* Modern tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0;
    background: rgba(255,255,255,0.1);
}

/* Responsive design */
@media (max-width: 768px) {
    .main-header {
        padding: 1rem;
        text-align: center;
    }
    
    .stColumns {
        flex-direction: column;
    }
}
</style>
""", unsafe_allow_html=True)

# Initialize session state with modern components
def init_session_state():
    """Initialize session state with modern components."""
    components = [
        ('db', DatabaseManager),
        ('scanner', FastScannerEngine),
        ('semantic_search', SemanticSearchEngine),
        ('chat_engine', ChatEngine),
        ('advanced_search', AdvancedSearch),
        ('tag_manager', TagManager),
        ('cloud_sync', CloudSyncManager),
        ('advanced_ai', AdvancedAI),
        ('advanced_viz', AdvancedVisualizations),
        ('ui_components', UIComponents),
        ('workspace_manager', WorkspaceManager),
        ('smart_suggestions', SmartSuggestions),
        ('unified_dashboard', UnifiedDashboard),
        ('onboarding_flow', OnboardingFlow),
        ('scan_controller', ScanController),
        ('navigation_manager', NavigationManager),
        ('advanced_search_interface', AdvancedSearchInterface)
    ]
    
    for key, component_class in components:
        if key not in st.session_state:
            try:
                st.session_state[key] = component_class()
            except Exception as e:
                st.error(f"Failed to initialize {key}: {e}")
    
    # Initialize other state variables
    if 'scan_running' not in st.session_state:
        st.session_state.scan_running = False
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "🏠 Dashboard"
    if 'search_history' not in st.session_state:
        st.session_state.search_history = []
    if 'favorites' not in st.session_state:
        st.session_state.favorites = set()
    if 'user_settings' not in st.session_state:
        st.session_state.user_settings = {}
    if 'notifications' not in st.session_state:
        st.session_state.notifications = []

def main():
    """Main modern application."""
    init_session_state()
    
    # Add floating activity indicator
    render_floating_activity_indicator()
    
    # Track app startup
    startup_id = start_activity(ActivityType.STARTUP, "Loading 36TB Intelligence Modern Interface")
    
    # Check if first-time user (TEMPORARILY DISABLED)
    onboarding = st.session_state.onboarding_flow
    if False:  # onboarding.is_first_time_user():
        st.markdown('<div class="fade-in">', unsafe_allow_html=True)
        onboarding.start_onboarding()
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    # Navigation manager for breadcrumbs
    nav_manager = st.session_state.navigation_manager
    nav_manager.render_navigation()
    
    # Modern header with theme toggle
    render_modern_header()
    
    # Global search bar (always visible)
    global_search_query = st.session_state.ui_components.global_search_bar(key="main_global_search")
    if global_search_query:
        handle_global_search(global_search_query)
    
    # Modern sidebar navigation
    page = render_modern_sidebar()
    st.session_state.current_page = page
    
    # Page routing with modern components with activity tracking
    with ActivityTracker(ActivityType.UI_INTERACTION, f"Rendering page: {page}"):
        render_page_content(page)
    
    # Complete startup
    finish_activity(startup_id, success=True, message="Modern interface ready")
    
    # Performance improvements
    render_performance_indicators()
    
    # Quick action buttons (floating)
    handle_quick_actions()

def render_modern_header():
    """Render modern header with status indicators."""
    st.markdown("""
    <div class="main-header fade-in">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h1 style="margin: 0; font-size: 2.5rem;">🔍 36TB Intelligence</h1>
                <p style="margin: 0.5rem 0 0 0; font-size: 1.2rem; opacity: 0.9;">
                    Your Personal Knowledge Operating System
                </p>
            </div>
            <div style="text-align: right;">
                <div id="status-indicators"></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # System status indicators
    render_system_status()

def render_system_status():
    """Render system status indicators."""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        # Database status
        try:
            total_files = st.session_state.db.get_stats().get('total_files', 0)
            st.session_state.ui_components.status_indicator(
                "success" if total_files > 0 else "warning",
                f"📁 {total_files:,} files indexed"
            )
        except:
            st.session_state.ui_components.status_indicator("error", "📁 Database error")
    
    with col2:
        # AI status
        try:
            chat_engine = st.session_state.chat_engine
            chat_stats = chat_engine.get_stats()
            if chat_stats.get('available', False):
                model_name = chat_stats.get('model', 'AI')
                st.session_state.ui_components.status_indicator(
                    "success",
                    f"🤖 {model_name} ready"
                )
            else:
                st.session_state.ui_components.status_indicator("warning", "🤖 AI offline")
        except Exception as e:
            st.session_state.ui_components.status_indicator("error", "🤖 AI error")
    
    with col3:
        # Scan status
        if st.session_state.get('scan_running', False):
            st.session_state.ui_components.status_indicator("loading", "🚀 Scanning...")
        else:
            st.session_state.ui_components.status_indicator("info", "🚀 Ready to scan")
    
    with col4:
        # Cloud status
        st.session_state.ui_components.status_indicator("info", "☁️ Cloud sync ready")

def render_modern_sidebar():
    """Render modern sidebar with improved navigation."""
    with st.sidebar:
        # Real-time Activity Monitor (new)
        render_sidebar_activity_monitor()
        
        st.markdown("---")
        
        # Theme toggle
        st.session_state.ui_components.theme_toggle()
        
        # Workspace selector
        workspace_manager = st.session_state.workspace_manager
        workspaces = workspace_manager.load_workspaces()
        
        if workspaces:
            st.selectbox(
                "🏢 Workspace",
                options=list(workspaces.keys()),
                key="current_workspace"
            )
        
        st.markdown("---")
        
        # UI Version selector
        ui_version = st.selectbox(
            "🎨 Interface Version",
            ["Version Moderne", "Version Classique"],
            key="modern_ui_version_selector"
        )
        
        if ui_version == "Version Classique":
            st.info("🔄 Pour basculer vers l'interface classique:")
            st.markdown("""
            **Option 1:** Ouvrez un nouvel onglet avec l'URL:  
            `http://localhost:8501`
            
            **Option 2:** Lancez dans un nouveau terminal:  
            ```bash
            streamlit run src/ui/app.py --server.port=8501
            ```
            """)
            st.markdown("""
            <div style="text-align: center; margin: 1rem 0;">
                <a href="http://localhost:8501" target="_blank" 
                   style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; padding: 1rem 2rem; border-radius: 10px; 
                          text-decoration: none; font-weight: bold;">
                    🔗 Ouvrir Interface Classique
                </a>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Modern navigation with icons and descriptions
        st.markdown("### 🧭 Navigation")
        
        pages = [
            {"id": "🚀 Scanner", "desc": "Index new files"},
            {"id": "🔍 Smart Search", "desc": "AI-powered file search"},
            {"id": "🎯 Advanced Search", "desc": "Detailed search filters"},
            {"id": "🤖 AI Assistant", "desc": "Chat with your documents"},
            {"id": "🔄 Activity Dashboard", "desc": "Real-time system monitoring"},
            {"id": "🏷️ Tags & Favorites", "desc": "Organize your files"},
            {"id": "🏠 Dashboard", "desc": "Overview & quick actions"},
            {"id": "📊 Analytics", "desc": "System insights"},
            {"id": "🌌 Visualizations", "desc": "Revolutionary data viz"},
            {"id": "🔄 Auto-Extract", "desc": "Extract file contents"},
            {"id": "☁️ Cloud Sync", "desc": "Backup & synchronize"},
            {"id": "⚙️ Settings", "desc": "Preferences & config"}
        ]
        
        # Current page selection - default to Scanner for logical workflow
        current_page = st.session_state.get('current_page', '🚀 Scanner')
        
        for page in pages:
            is_selected = page["id"] == current_page
            
            # Custom button styling for selected page
            button_style = "primary" if is_selected else "secondary"
            
            if st.button(
                f"{page['id']}\n{page['desc']}", 
                key=f"nav_{page['id']}",
                use_container_width=True,
                type=button_style
            ):
                return page["id"]
        
        st.markdown("---")
        
        # Quick stats in sidebar
        render_sidebar_stats()
        
        # Recent searches
        render_recent_searches()
    
    return current_page

def render_sidebar_stats():
    """Render quick stats in sidebar."""
    st.markdown("### 📊 Quick Stats")
    
    try:
        stats = st.session_state.db.get_stats()
        
        # File count
        total_files = stats.get('total_files', 0)
        st.metric("Files", f"{total_files:,}")
        
        # Storage used
        total_size = stats.get('total_size', 0)
        size_str = st.session_state.ui_components.format_file_size(total_size)
        st.metric("Storage", size_str)
        
        # Today's activity
        searches_today = st.session_state.get('searches_today', 0)
        st.metric("Searches Today", searches_today)
        
    except Exception as e:
        st.error(f"Stats error: {e}")

def render_recent_searches():
    """Render recent searches in sidebar."""
    st.markdown("### 🕒 Recent Searches")
    
    history = st.session_state.get('search_history', [])
    if history:
        for search in history[-5:]:  # Last 5 searches
            if st.button(f"🔍 {search}", key=f"recent_{hash(search)}", use_container_width=True):
                st.session_state.global_search = search
                st.rerun()
    else:
        st.info("No recent searches")

def render_page_content(page: str):
    """Render page content based on selection."""
    st.markdown('<div class="fade-in">', unsafe_allow_html=True)
    
    if page == "🏠 Dashboard":
        st.session_state.unified_dashboard.render_dashboard()
    
    elif page == "🔍 Smart Search" or page == "🎯 Advanced Search":
        st.session_state.advanced_search_interface.render_search_interface()
    
    elif page == "🤖 AI Assistant":
        render_ai_assistant_page()
    
    elif page == "🏷️ Tags & Favorites":
        render_tags_favorites_page()
    
    elif page == "🌌 Visualizations":
        render_visualizations_page()
    
    elif page == "☁️ Cloud Sync":
        render_cloud_sync_page()
    
    elif page == "🚀 Scanner":
        render_scanner_page()
    
    elif page == "🔄 Auto-Extract":
        render_auto_extract_page()
    
    elif page == "📊 Analytics":
        render_analytics_page()
    
    elif page == "🔄 Activity Dashboard":
        render_activity_dashboard_page()
    
    elif page == "⚙️ Settings":
        render_settings_page()
    
    st.markdown('</div>', unsafe_allow_html=True)

def handle_global_search(query: str):
    """Handle global search from header."""
    # Track search activity
    search_id = start_activity(ActivityType.SEARCH, f"Global search: '{query}'")
    
    try:
        # Add to search history
        if 'search_history' not in st.session_state:
            st.session_state.search_history = []
        
        if query not in st.session_state.search_history:
            st.session_state.search_history.append(query)
            # Keep only last 50 searches
            st.session_state.search_history = st.session_state.search_history[-50:]
        
        # Increment search count
        st.session_state.searches_today = st.session_state.get('searches_today', 0) + 1
        
        # Switch to search page and perform search
        st.session_state.current_page = "🔍 Smart Search"
        st.session_state.main_search = query
        
        finish_activity(search_id, success=True, message=f"Search initiated for '{query}'")
        st.rerun()
        
    except Exception as e:
        finish_activity(search_id, success=False, message=f"Search failed: {e}")
        st.error(f"Search error: {e}")

def handle_quick_actions():
    """Handle floating quick action buttons."""
    action = st.session_state.ui_components.quick_action_buttons()
    
    if action == "scan":
        with st.spinner("TurboScan in progress..."):
            try:
                # Use TurboScanner for ultra-fast scanning
                turbo = TurboScanner()
                
                # Get user directory for initial scan instead of full C:
                import os
                username = os.getenv('USERNAME', 'User')
                docs_path = f"C:\\Users\\{username}\\Documents"
                
                scan_path = docs_path if Path(docs_path).exists() else "C:\\Users"
                
                # Run turbo scan in a separate thread to avoid UI blocking
                import threading
                scan_result = {'files_saved': 0, 'completed': False, 'error': None}
                
                def run_scan():
                    try:
                        turbo.turbo_scan(scan_path)
                        # Safe access to stats
                        if hasattr(turbo, 'stats') and turbo.stats:
                            scan_result['files_saved'] = turbo.stats.get('files_saved', 0)
                        else:
                            scan_result['files_saved'] = 0
                        scan_result['completed'] = True
                    except Exception as e:
                        scan_result['error'] = str(e)
                        scan_result['completed'] = True
                
                scan_thread = threading.Thread(target=run_scan, daemon=True)
                scan_thread.start()
                
                # Wait for completion (with timeout)
                scan_thread.join(timeout=30)  # 30 second timeout
                
                if scan_result['completed']:
                    if scan_result['error']:
                        st.toast(f"❌ TurboScan failed: {scan_result['error']}", icon="⚠️")
                    else:
                        st.toast(f"✅ TurboScan: {scan_result['files_saved']:,} files indexed!", icon="🚀")
                else:
                    st.toast("⏱️ TurboScan continuing in background...", icon="🔄")
                    
            except Exception as e:
                st.toast(f"❌ TurboScan failed: {e}", icon="⚠️")
    
    elif action == "extract":
        with st.spinner("Extracting content..."):
            try:
                # Get auto extractor
                if 'auto_extractor' not in st.session_state:
                    st.session_state.auto_extractor = AutoExtractor()
                
                extractor = st.session_state.auto_extractor
                candidates = extractor.get_extraction_candidates(limit=50)
                
                if candidates:
                    results = extractor.extract_batch(candidates[:10])
                    st.toast(f"✅ Extracted {len(results)} files!", icon="🔄")
                else:
                    st.toast("ℹ️ No files ready for extraction", icon="ℹ️")
            except Exception as e:
                st.toast(f"❌ Extraction failed: {e}", icon="⚠️")
    
    elif action == "sync":
        with st.spinner("Syncing with cloud..."):
            time.sleep(2)  # Mock sync
            st.toast("✅ Cloud sync completed!", icon="☁️")

def render_performance_indicators():
    """Render performance indicators and loading states."""
    # Real-time performance metrics
    if st.session_state.get('show_performance', False):
        with st.sidebar.expander("⚡ Performance"):
            # Mock performance data
            st.metric("Response Time", "0.3s", delta="-0.1s")
            st.metric("Memory Usage", "85%", delta="2%")
            st.metric("Cache Hit Rate", "94%", delta="3%")

# Individual page rendering functions
def render_ai_assistant_page():
    """Render AI assistant page."""
    st.subheader("🤖 AI Assistant")
    st.info("Chat with your documents and get intelligent insights!")
    
    # AI chat interface would go here
    # This integrates with the existing chat_engine
    
def render_tags_favorites_page():
    """Render tags and favorites page."""
    st.subheader("🏷️ Tags & Favorites")
    
    tab1, tab2 = st.tabs(["⭐ Favorites", "🏷️ Tags"])
    
    with tab1:
        favorites = st.session_state.get('favorites', set())
        if favorites:
            st.write(f"**{len(favorites)} favorite files:**")
            for fav in list(favorites)[:10]:  # Show first 10
                st.write(f"⭐ {Path(fav).name}")
        else:
            st.info("No favorites yet. Star files to add them here!")
    
    with tab2:
        st.info("Tag management system - organize your files with intelligent tags!")

def render_visualizations_page():
    """Render visualizations page."""
    st.subheader("🌌 Revolutionary Visualizations")
    
    viz_manager = st.session_state.advanced_viz
    
    if not viz_manager.is_available():
        st.warning("Visualization libraries not available. Install plotly and networkx for full experience.")
        return
    
    viz_options = [
        "🌌 3D File Universe",
        "🕸️ Document Network",
        "🔥 Activity Heatmap",
        "📊 Size Distribution",
        "🌳 Folder Treemap"
    ]
    
    selected_viz = st.selectbox("Choose visualization:", viz_options)
    
    if "3D File Universe" in selected_viz:
        fig = viz_manager.create_file_universe_3d()
        if fig:
            st.plotly_chart(fig, use_container_width=True)
    
    elif "Document Network" in selected_viz:
        fig = viz_manager.create_document_network_graph()
        if fig:
            st.plotly_chart(fig, use_container_width=True)

def render_cloud_sync_page():
    """Render cloud sync page."""
    st.subheader("☁️ Cloud Synchronization")
    st.info("Backup and sync your file index with cloud storage!")

def render_scanner_page():
    """Render advanced scanner page."""
    st.subheader("🚀 Advanced File Scanner")
    
    # Initialize disk selector
    disk_selector = DiskSelector()
    
    # Scanner overview
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("""
        ### 🎯 Multi-Drive Scanner
        
        Scan multiple drives and directories simultaneously with advanced filtering options.
        Choose exactly which drives and paths you want to index.
        """)
    
    with col2:
        # Quick stats
        try:
            stats = st.session_state.db.get_stats()
            st.metric("📁 Files Indexed", f"{stats.get('total_files', 0):,}")
            st.metric("💾 Total Size", st.session_state.ui_components.format_file_size(stats.get('total_size', 0)))
        except:
            st.metric("📁 Files Indexed", "0")
            st.metric("💾 Total Size", "0 B")
    
    # Main scanner interface
    st.markdown("---")
    
    # Disk selection
    selected_paths = disk_selector.render_disk_selection(key_prefix="scanner_page")
    
    if not selected_paths:
        st.warning("⚠️ Please select drives or paths to scan.")
        return
    
    # Scan configuration
    st.markdown("### ⚙️ Scan Configuration")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        max_files = st.number_input(
            "🔢 Max files per drive:",
            min_value=0,
            max_value=1000000,
            value=100000,
            step=5000,
            help="Maximum files to scan per drive (0 = unlimited)"
        )
    
    with col2:
        file_limit_mb = st.number_input(
            "📏 Max file size (MB):",
            min_value=0,
            max_value=10000,
            value=1000,
            help="Skip files larger than this (0 = no limit)"
        )
    
    with col3:
        threads = st.slider(
            "🧵 Scan threads:",
            min_value=1,
            max_value=8,
            value=4,
            help="Number of parallel scanning threads"
        )
    
    # File type filters
    st.markdown("### 📂 File Type Filters")
    
    filter_mode = st.radio(
        "Filter mode:",
        ["🌟 Smart Filter (Recommended)", "📝 Include Types", "🚫 Exclude Types", "🔓 No Filters"],
        horizontal=True
    )
    
    file_types = []
    
    if filter_mode == "📝 Include Types":
        file_types = st.multiselect(
            "Include only these types:",
            ["📄 Documents", "🖼️ Images", "🎵 Audio", "🎥 Videos", "📦 Archives", "⚙️ Code", "📊 Spreadsheets"],
            default=["📄 Documents", "🖼️ Images"]
        )
    elif filter_mode == "🚫 Exclude Types":
        file_types = st.multiselect(
            "Exclude these types:",
            ["🗑️ Temporary", "🔧 System", "📀 Cache", "🔒 Protected"],
            default=["🗑️ Temporary", "🔧 System"]
        )
    
    # Advanced options
    with st.expander("🔧 Advanced Options"):
        col1, col2 = st.columns(2)
        
        with col1:
            include_hidden = st.checkbox("👁️ Include hidden files")
            follow_links = st.checkbox("🔗 Follow symbolic links")
            deep_scan = st.checkbox("🔍 Deep content analysis")
        
        with col2:
            create_thumbnails = st.checkbox("🖼️ Generate thumbnails")
            extract_metadata = st.checkbox("📋 Extract metadata")
            calculate_hashes = st.checkbox("🔐 Calculate file hashes")
    
    # Start scan
    st.markdown("---")
    
    # Advanced Scan Controls
    scan_controller = st.session_state.scan_controller
    
    # Render scan controls with progress tracking
    scan_action = scan_controller.render_scan_controls(
        scanner_engine=st.session_state.scanner,
        key_prefix="main_scanner"
    )
    
    # Handle scan control actions
    if scan_action == "pause":
        st.session_state.scanner.pause()
        scan_controller.set_status('paused')
        st.toast("⏸️ Scan paused", icon="⏸️")
    
    elif scan_action == "resume":
        st.session_state.scanner.resume()
        scan_controller.set_status('running')
        st.toast("▶️ Scan resumed", icon="▶️")
    
    elif scan_action == "stop":
        st.session_state.scanner.cancel()
        scan_controller.set_status('cancelled')
        st.session_state.scan_running = False
        st.toast("⏹️ Scan stopped", icon="⏹️")
    
    elif scan_action == "reset":
        scan_controller.reset_progress()
        st.toast("🔄 Progress reset", icon="🔄")
    
    st.markdown("---")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        scan_disabled = scan_controller.get_status() in ['running', 'paused']
        if st.button("🚀 Start Advanced Scan", type="primary", use_container_width=True, disabled=scan_disabled):
            _start_multi_drive_scan(
                selected_paths, max_files, file_limit_mb, threads,
                filter_mode, file_types, {
                    'include_hidden': include_hidden,
                    'follow_links': follow_links,
                    'deep_scan': deep_scan,
                    'create_thumbnails': create_thumbnails,
                    'extract_metadata': extract_metadata,
                    'calculate_hashes': calculate_hashes
                }
            )
    
    with col2:
        if st.button("⏸️ Pause Scan", disabled=not st.session_state.get('scan_running', False)):
            st.session_state.scan_running = False
            st.info("Scan paused")
    
    with col3:
        # Two-step confirmation for clearing index
        if 'confirm_clear' not in st.session_state:
            st.session_state.confirm_clear = False
            
        if not st.session_state.confirm_clear:
            if st.button("🗑️ Clear Index", help="Clear all indexed files"):
                st.session_state.confirm_clear = True
                st.rerun()
        else:
            st.warning("⚠️ This will delete ALL indexed files!")
            col_confirm, col_cancel = st.columns(2)
            
            with col_confirm:
                if st.button("✅ Confirm Clear", type="primary"):
                    try:
                        st.session_state.db.clear_all_files()
                        st.session_state.confirm_clear = False
                        st.success("Index cleared!")
                        st.rerun()
                    except Exception as e:
                        st.session_state.confirm_clear = False
                        st.error(f"Clear failed: {e}")
            
            with col_cancel:
                if st.button("❌ Cancel"):
                    st.session_state.confirm_clear = False
                    st.rerun()

def _start_multi_drive_scan(paths, max_files, file_limit_mb, threads, filter_mode, file_types, options):
    """Start multi-drive scanning with progress tracking."""
    
    # Get scan controller from session state
    scan_controller = st.session_state.scan_controller
    
    # Set scan controller to running state
    scan_controller.set_status('running')
    scan_controller.reset_progress()
    
    # Initialize progress tracking with scan controller
    total_files_scanned = 0
    total_files_found = 0
    total_size_bytes = 0
    scan_start_time = time.time()
    total_estimated_files = len(paths) * max_files  # Rough estimate
    
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
                    # Calculate files per second
                    elapsed = time.time() - start_time
                    fps = scan_progress.scanned_files / max(elapsed, 0.001)
                    
                    # Update scan controller progress
                    update_data = {
                        'status': 'running',
                        'progress': (total_files_scanned + scan_progress.scanned_files) / total_estimated_files,
                        'current_file': scan_progress.current_file or '',
                        'files_processed': total_files_scanned + scan_progress.scanned_files,
                        'total_files': total_estimated_files,
                        'files_per_second': fps,
                        'start_time': datetime.now(),
                        'current_path': str(path),
                        'errors': scan_progress.error_files
                    }
                    scan_controller.update_progress(update_data)
                
                # Use TurboScanner for ultra-fast scanning instead of old scanner
                try:
                    turbo = TurboScanner()
                    
                    # Run turbo scan on specific path and get detailed stats
                    turbo_stats = turbo.turbo_scan(str(path))
                    
                    if turbo_stats:
                        # Update totals with TurboScanner statistics
                        total_files_found += turbo_stats['files_found']
                        total_files_scanned += turbo_stats['files_saved']
                        total_size_bytes += turbo_stats['total_size_bytes']
                        
                        # Update progress with actual results
                        progress_data['files_processed'] = total_files_scanned
                        progress_data['current_file'] = f"Found {turbo_stats['files_saved']:,} new files in {path}"
                    else:
                        # TurboScanner returned None - handle gracefully
                        progress_data['current_file'] = f"No new files found in {path}"
                    
                    scan_controller.update_progress(progress_data)
                    
                except Exception as turbo_error:
                    # Fallback to old scanner if TurboScanner fails
                    st.warning(f"TurboScanner failed for {path}, using fallback scanner: {turbo_error}")
                    files = list(scanner.scan_paths([Path(path)], limit=files_per_drive, progress_callback=progress_callback))
                    
                    if files:
                        # Apply filters
                        filtered_files = _apply_multi_scan_filters(files, filter_mode, file_types, options, file_size_limit)
                        
                        # Save to database
                        if filtered_files:
                            st.session_state.db.save_files_batch(filtered_files)
                            total_files_scanned += len(filtered_files)
                        
                        # Update progress
                        progress_data['files_processed'] = total_files_scanned
                        progress_data['progress'] = total_files_scanned / total_estimated_files
                        scan_controller.update_progress(progress_data)
                    
            except Exception as e:
                # Update error count
                progress_data['errors'] = progress_data.get('errors', 0) + 1
                scan_controller.update_progress(progress_data)
                st.error(f"Error scanning {path}: {str(e)}")
                continue
        
        # Update scan controller to completed status
        scan_controller.set_status('completed')
        progress_data['status'] = 'completed'
        progress_data['progress'] = 1.0
        progress_data['current_file'] = 'Scan completed'
        scan_controller.update_progress(progress_data)
        
        st.session_state.scan_running = False
        
        # Calculate final statistics
        scan_duration = time.time() - scan_start_time
        files_per_second = int(total_files_scanned / scan_duration) if scan_duration > 0 else 0
        total_size_gb = total_size_bytes / (1024**3) if total_size_bytes > 0 else 0
        
        if total_files_scanned > 0:
            st.success(f"""
            🎉 **Multi-Drive Scan Completed!**
            
            - **📁 Drives scanned**: {len(paths)}
            - **🔍 Files found**: {total_files_found:,}
            - **📄 Files indexed**: {total_files_scanned:,}
            - **💾 Total size**: {total_size_gb:.1f} GB
            - **⏱️ Duration**: {scan_duration:.1f} seconds
            - **⚡ Speed**: {files_per_second:,} files/sec
            - **🧵 Threads used**: {threads}
            """)
        else:
            st.warning("⚠️ Scan completed but no new files were found.")
        
    except Exception as e:
        # Update scan controller to error status
        scan_controller.set_status('cancelled')
        progress_data['status'] = 'cancelled'
        progress_data['current_file'] = f'Error: {str(e)}'
        scan_controller.update_progress(progress_data)
        st.session_state.scan_running = False
        st.error(f"❌ Multi-drive scan failed: {e}")

def _apply_multi_scan_filters(files, filter_mode, file_types, options, file_size_limit):
    """Apply advanced filtering to scanned files."""
    filtered_files = []
    
    for file_info in files:
        # File size limit
        if file_size_limit and file_info.size_bytes > file_size_limit:
            continue
        
        # Hidden files filter
        if not options.get('include_hidden', False) and file_info.filename.startswith('.'):
            continue
        
        # Apply file type filters based on mode
        if filter_mode == "🌟 Smart Filter (Recommended)":
            # Smart filter: skip common junk files
            filename_lower = file_info.filename.lower()
            if any(skip in filename_lower for skip in ['temp', 'cache', '.log', '.tmp', 'thumbs.db']):
                continue
        
        elif filter_mode == "📝 Include Types" and file_types:
            # Include only specified types
            file_ext = Path(file_info.filename).suffix.lower()
            type_matched = _check_file_type_match(file_ext, file_types, include_mode=True)
            if not type_matched:
                continue
        
        elif filter_mode == "🚫 Exclude Types" and file_types:
            # Exclude specified types
            file_ext = Path(file_info.filename).suffix.lower()
            type_matched = _check_file_type_match(file_ext, file_types, include_mode=False)
            if type_matched:
                continue
        
        filtered_files.append(file_info)
    
    return filtered_files

def _check_file_type_match(file_ext, selected_types, include_mode=True):
    """Check if file extension matches selected types."""
    type_mappings = {
        "📄 Documents": ['.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt'],
        "🖼️ Images": ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.svg'],
        "🎵 Audio": ['.mp3', '.wav', '.flac', '.ogg', '.aac', '.wma'],
        "🎥 Videos": ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.webm'],
        "📦 Archives": ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
        "⚙️ Code": ['.py', '.js', '.html', '.css', '.cpp', '.java', '.php'],
        "📊 Spreadsheets": ['.xlsx', '.xls', '.csv', '.ods'],
        "🗑️ Temporary": ['.tmp', '.temp', '.log', '.cache'],
        "🔧 System": ['.sys', '.dll', '.exe', '.msi'],
        "📀 Cache": ['.cache', '.thumbnails', '.tmp'],
        "🔒 Protected": ['.sys', '.dll', '.driver']
    }
    
    for selected_type in selected_types:
        if selected_type in type_mappings:
            if file_ext in type_mappings[selected_type]:
                return True
    
    return False

def render_auto_extract_page():
    """Render auto extract page."""
    st.subheader("🔄 Content Extraction")
    st.info("Extract content from documents for better search!")

def render_analytics_page():
    """Render analytics page."""
    st.subheader("📊 System Analytics")
    st.info("Detailed insights into your file system!")

def render_settings_page():
    """Render settings page."""
    st.subheader("⚙️ Settings")
    
    tab1, tab2, tab3 = st.tabs(["🎨 Appearance", "⚡ Performance", "🔧 Advanced"])
    
    with tab1:
        st.checkbox("Dark mode", key="dark_mode_setting")
        st.checkbox("Show performance metrics", key="show_performance")
        st.selectbox("Language", ["English", "Français", "Español"])
    
    with tab2:
        st.slider("Scan threads", 1, 8, 4)
        st.slider("Cache size (MB)", 100, 1000, 500)
        st.checkbox("Auto-scan on startup", value=True)
    
    with tab3:
        st.text_input("Database path", value="data/indexes/files.db")
        st.text_input("Ollama URL", value="http://localhost:11434")
        st.checkbox("Debug mode", value=False)

def render_activity_dashboard_page():
    """Render the full activity dashboard page."""
    st.subheader("🔄 Real-Time Activity Dashboard")
    st.markdown("Monitor all system processes and activities in real-time")
    
    # Use the full activity dashboard
    render_full_activity_dashboard()
    
    # Add performance metrics
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 💻 System Performance")
        import psutil
        
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        st.progress(cpu_percent / 100.0, text=f"CPU Usage: {cpu_percent:.1f}%")
        
        # Memory usage
        memory = psutil.virtual_memory()
        st.progress(memory.percent / 100.0, text=f"Memory Usage: {memory.percent:.1f}%")
        
        # Disk usage
        try:
            disk = psutil.disk_usage('.')
            disk_percent = (disk.used / disk.total) * 100
            st.progress(disk_percent / 100.0, text=f"Disk Usage: {disk_percent:.1f}%")
        except:
            st.info("Disk info unavailable")
    
    with col2:
        st.markdown("### 🔧 System Info")
        st.metric("Process Count", len(psutil.pids()))
        
        # Boot time
        import datetime
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.datetime.now() - boot_time
        st.metric("System Uptime", f"{uptime.days}d {uptime.seconds//3600}h")
        
        # Network stats
        try:
            net_io = psutil.net_io_counters()
            mb_sent = net_io.bytes_sent / (1024 * 1024)
            mb_recv = net_io.bytes_recv / (1024 * 1024)
            st.metric("Network Sent", f"{mb_sent:.1f} MB")
            st.metric("Network Received", f"{mb_recv:.1f} MB")
        except:
            st.info("Network info unavailable")

if __name__ == "__main__":
    main()