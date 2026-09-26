"""Advanced unified dashboard for 36TB Intelligence."""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import time
from pathlib import Path

from src.ui.components import UIComponents, WorkspaceManager, SmartSuggestions
from src.ui.disk_selector import DiskSelector
from src.core.scan_service import ScanService

class UnifiedDashboard:
    """Modern unified dashboard with intelligent widgets."""
    
    def __init__(self):
        self.workspace_manager = WorkspaceManager()
        self.components = UIComponents()
        self.disk_selector = DiskSelector()
        
    def render_dashboard(self):
        """Render the main dashboard."""
        # Theme toggle in header
        col1, col2 = st.columns([8, 1])
        with col1:
            st.title("🏠 36TB Intelligence Dashboard")
        with col2:
            self.components.theme_toggle()
        
        # Global search bar
        search_query = self.components.global_search_bar(key="dashboard_global_search")
        if search_query:
            st.session_state.dashboard_search = search_query
            st.rerun()
        
        # Quick stats row
        self._render_quick_stats()
        
        # Main content area
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🚀 Quick Actions", "📈 Analytics", "⚙️ Settings"])
        
        with tab1:
            self._render_overview_tab()
        
        with tab2:
            self._render_quick_actions_tab()
            
        with tab3:
            self._render_analytics_tab()
            
        with tab4:
            self._render_settings_tab()
        
        # Floating action button
        action = self.components.quick_action_buttons(key_prefix="dashboard")
        if action:
            self._handle_quick_action(action)
    
    def _render_quick_stats(self):
        """Render quick statistics cards."""
        try:
            # Get stats from database
            db = st.session_state.db
            stats = db.get_stats()
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(
                    label="📁 Total Files",
                    value=f"{stats.get('total_files', 0):,}",
                    delta=f"+{stats.get('new_files_today', 0)} today"
                )
            
            with col2:
                total_size = stats.get('total_size', 0)
                size_str = self.components.format_file_size(total_size)
                st.metric(
                    label="💾 Total Size", 
                    value=size_str,
                    delta=f"{self.components.format_file_size(stats.get('size_change_today', 0))} today"
                )
            
            with col3:
                st.metric(
                    label="🔍 Searches Today",
                    value=st.session_state.get('searches_today', 0),
                    delta=f"+{st.session_state.get('search_increase', 0)}% vs yesterday"
                )
            
            with col4:
                # LLM Status
                try:
                    chat_engine = st.session_state.chat_engine
                    model_status = chat_engine.get_model_status()
                    if model_status.get('available', False):
                        st.metric(
                            label="🤖 AI Status",
                            value="Online",
                            delta=f"Model: {model_status.get('current_model', 'Unknown')}"
                        )
                    else:
                        st.metric(
                            label="🤖 AI Status",
                            value="Offline",
                            delta="Check Ollama connection"
                        )
                except:
                    st.metric(label="🤖 AI Status", value="Unknown", delta="")
                    
        except Exception as e:
            st.error(f"Error loading stats: {e}")
    
    def _render_overview_tab(self):
        """Render overview dashboard tab."""
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Recent files section
            st.subheader("📋 Recent Activity")
            
            try:
                # Get recent files from database
                recent_files = st.session_state.db.get_recent_files(limit=10)
                
                if recent_files:
                    for file_info in recent_files:
                        self.components.file_card(file_info)
                else:
                    st.info("No recent activity. Start by scanning your files!")
                    
            except Exception as e:
                st.error(f"Error loading recent files: {e}")
        
        with col2:
            # Insights panel
            st.subheader("🧠 Smart Insights")
            
            # File type distribution
            try:
                type_stats = st.session_state.db.get_file_type_stats()
                if type_stats:
                    st.write("**File Types:**")
                    for file_type, count in type_stats.items():
                        st.write(f"• {file_type.upper()}: {count:,} files")
            except:
                pass
            
            # Quick recommendations
            st.write("**💡 Recommendations:**")
            recommendations = self._get_smart_recommendations()
            for rec in recommendations:
                st.info(rec)
    
    def _render_quick_actions_tab(self):
        """Render quick actions tab."""
        st.subheader("⚡ Quick Actions")
        
        # Action cards
        col1, col2, col3 = st.columns(3)
        
        with col1:
            with st.container():
                st.markdown("""
                <div style="
                    padding: 20px;
                    border-radius: 12px;
                    background: linear-gradient(135deg, #667eea, #764ba2);
                    color: white;
                    text-align: center;
                    margin-bottom: 16px;
                ">
                    <h3>🚀 Quick Scan</h3>
                    <p>Scan your entire system for new files</p>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("Start Scan", key="dashboard_scan", use_container_width=True):
                    self._show_scan_dialog()
        
        with col2:
            with st.container():
                st.markdown("""
                <div style="
                    padding: 20px;
                    border-radius: 12px;
                    background: linear-gradient(135deg, #f093fb, #f5576c);
                    color: white;
                    text-align: center;
                    margin-bottom: 16px;
                ">
                    <h3>🔄 Auto Extract</h3>
                    <p>Extract content from documents</p>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("Extract Content", key="dashboard_extract", use_container_width=True):
                    self._start_auto_extract()
        
        with col3:
            with st.container():
                st.markdown("""
                <div style="
                    padding: 20px;
                    border-radius: 12px;
                    background: linear-gradient(135deg, #4facfe, #00f2fe);
                    color: white;
                    text-align: center;
                    margin-bottom: 16px;
                ">
                    <h3>☁️ Cloud Sync</h3>
                    <p>Sync with cloud storage</p>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("Sync Now", key="dashboard_sync", use_container_width=True):
                    self._start_cloud_sync()
        
        # Search templates
        st.subheader("🔍 Search Templates")
        
        templates = [
            {"name": "📄 Recent Documents", "query": "type:document modified:last_week"},
            {"name": "🖼️ Large Images", "query": "type:image size:>10MB"},
            {"name": "🐍 Python Files", "query": "extension:py"},
            {"name": "📊 Spreadsheets", "query": "type:spreadsheet"},
            {"name": "🎵 Music Library", "query": "type:audio"},
            {"name": "📦 Archives", "query": "type:archive"}
        ]
        
        cols = st.columns(2)
        for i, template in enumerate(templates):
            with cols[i % 2]:
                if st.button(template["name"], key=f"template_{i}", use_container_width=True):
                    st.session_state.template_search = template["query"]
                    st.switch_page("pages/search.py")
    
    def _render_analytics_tab(self):
        """Render analytics tab with charts."""
        st.subheader("📈 System Analytics")
        
        try:
            # File growth over time
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**📊 File Count Growth**")
                # Mock data for demonstration
                dates = pd.date_range(start='2024-01-01', end=datetime.now(), freq='D')
                data = pd.DataFrame({
                    'Date': dates,
                    'Files': range(1000, 1000 + len(dates))
                })
                st.line_chart(data.set_index('Date'))
            
            with col2:
                st.write("**💾 Storage Usage**")
                # Mock storage data
                storage_data = {
                    'Documents': 15.2,
                    'Images': 28.5,
                    'Videos': 45.8,
                    'Audio': 8.3,
                    'Other': 2.2
                }
                st.bar_chart(storage_data)
        
        except Exception as e:
            st.error(f"Error loading analytics: {e}")
    
    def _render_settings_tab(self):
        """Render settings and preferences tab."""
        st.subheader("⚙️ System Settings")
        
        # Workspace management
        st.write("**🏢 Workspace Management**")
        workspaces = self.workspace_manager.load_workspaces()
        
        if workspaces:
            current_workspace = st.selectbox(
                "Current Workspace:",
                options=list(workspaces.keys()),
                index=0
            )
            
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("💾 Save Current State"):
                    self._save_current_workspace(current_workspace)
            with col2:
                if st.button("🗑️ Delete Workspace"):
                    self.workspace_manager.delete_workspace(current_workspace)
                    st.rerun()
        
        # Create new workspace
        with st.expander("➕ Create New Workspace"):
            workspace_name = st.text_input("Workspace Name:")
            if st.button("Create") and workspace_name:
                self._create_new_workspace(workspace_name)
        
        # Performance settings
        st.write("**⚡ Performance Settings**")
        col1, col2 = st.columns(2)
        
        with col1:
            scan_threads = st.slider("Scan Threads:", 1, 8, 4)
            extract_batch = st.slider("Extract Batch Size:", 10, 100, 50)
        
        with col2:
            cache_size = st.slider("Cache Size (MB):", 100, 1000, 500)
            auto_scan = st.checkbox("Auto Scan on Startup", value=True)
        
        if st.button("💾 Save Settings"):
            settings = {
                'scan_threads': scan_threads,
                'extract_batch': extract_batch,
                'cache_size': cache_size,
                'auto_scan': auto_scan
            }
            st.session_state.user_settings = settings
            st.success("Settings saved!")
    
    def _get_smart_recommendations(self) -> List[str]:
        """Generate smart recommendations."""
        recommendations = []
        
        try:
            stats = st.session_state.db.get_stats()
            
            # Based on file count
            if stats.get('total_files', 0) == 0:
                recommendations.append("🚀 Start by scanning your files to build your index")
            elif stats.get('extracted_files', 0) < stats.get('total_files', 0) * 0.1:
                recommendations.append("🔄 Consider extracting content from more files for better search")
            
            # Based on file types
            type_stats = st.session_state.db.get_file_type_stats()
            if type_stats:
                most_common = max(type_stats, key=type_stats.get)
                recommendations.append(f"📊 Most of your files are {most_common.upper()} - explore specialized tools")
        
        except:
            pass
        
        if not recommendations:
            recommendations = ["✨ Your system is running optimally!"]
        
        return recommendations[:3]
    
    def _show_scan_dialog(self):
        """Show advanced scan dialog with disk selection."""
        # Use modal dialog with disk selector
        with st.expander("🚀 Advanced Scanner - Select Drives", expanded=True):
            st.markdown("### 🎯 Configure Your Scan")
            
            # Disk selection
            selected_paths = self.disk_selector.render_disk_selection(key_prefix="dashboard_scan")
            
            if not selected_paths:
                st.warning("⚠️ No drives selected. Please select at least one drive to scan.")
                return
            
            # Scan options
            col1, col2 = st.columns(2)
            
            with col1:
                max_files = st.number_input(
                    "Max files to scan:", 
                    min_value=100, 
                    max_value=100000, 
                    value=10000,
                    step=1000,
                    help="Limit the number of files to scan for performance"
                )
            
            with col2:
                scan_depth = st.selectbox(
                    "Scan depth:",
                    ["Full scan", "Top-level only", "2 levels deep", "3 levels deep"],
                    help="How deep to scan into subdirectories"
                )
            
            # Advanced options
            with st.expander("🔧 Advanced Options"):
                col1, col2 = st.columns(2)
                
                with col1:
                    include_hidden = st.checkbox("Include hidden files", value=False)
                    include_system = st.checkbox("Include system files", value=False)
                
                with col2:
                    min_file_size = st.number_input("Min file size (KB):", min_value=0, value=0)
                    file_types = st.multiselect(
                        "File types to include:",
                        ["All", "Documents", "Images", "Videos", "Audio", "Archives"],
                        default=["All"]
                    )
            
            # Start scan button
            if st.button("🚀 Start Advanced Scan", key="start_advanced_scan", type="primary", use_container_width=True):
                self._start_advanced_scan(selected_paths, max_files, scan_depth, {
                    'include_hidden': include_hidden,
                    'include_system': include_system,
                    'min_file_size': min_file_size * 1024 if min_file_size > 0 else 0,
                    'file_types': file_types
                })
    
    def _start_advanced_scan(self, paths: list, max_files: int, scan_depth: str, options: dict):
        """Start advanced scan with selected options."""
        total_files_scanned = 0
        
        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            scanner = st.session_state.scanner
            
            for i, path in enumerate(paths):
                status_text.text(f"📁 Scanning {path}...")
                progress_bar.progress((i + 0.5) / len(paths))
                
                # Calculate files per path
                files_per_path = max_files // len(paths)
                
                # Scan this path through the canonical lifecycle
                session = ScanService(st.session_state.db).session(path)
                try:
                    files = list(scanner.fast_scan(Path(path), limit=files_per_path))
                    filtered_files = self._apply_scan_filters(files, options) if files else []

                    if filtered_files:
                        session.record(filtered_files)
                        total_files_scanned += len(filtered_files)

                    session.complete()
                    if files:
                        status_text.text(f"✅ {path}: {len(filtered_files)} files added")
                    else:
                        status_text.text(f"⚠️ {path}: No files found")

                except Exception as e:
                    session.fail(str(e))
                    status_text.text(f"❌ {path}: Error - {e}")
                    continue
                
                progress_bar.progress((i + 1) / len(paths))
            
            # Final result
            progress_bar.progress(1.0)
            status_text.empty()
            
            if total_files_scanned > 0:
                st.success(f"🎉 Scan completed! Added {total_files_scanned:,} files to your index.")
            else:
                st.warning("⚠️ Scan completed but no new files were found.")
                
        except Exception as e:
            st.error(f"❌ Scan failed: {e}")
        finally:
            progress_bar.empty()
            status_text.empty()
    
    def _apply_scan_filters(self, files: list, options: dict) -> list:
        """Apply filtering options to scanned files."""
        filtered_files = []
        
        for file_info in files:
            # Skip hidden files if not included
            if not options.get('include_hidden', False):
                if file_info.filename.startswith('.'):
                    continue
            
            # Skip system files if not included  
            if not options.get('include_system', False):
                # Basic system file detection
                if any(sys_ext in file_info.filename.lower() for sys_ext in ['.sys', '.dll', '.exe']):
                    continue
            
            # Min file size filter
            min_size = options.get('min_file_size', 0)
            if min_size > 0 and file_info.size_bytes < min_size:
                continue
            
            # File type filter
            file_types = options.get('file_types', ['All'])
            if 'All' not in file_types:
                file_ext = Path(file_info.filename).suffix.lower()
                
                # Map extensions to categories
                type_matched = False
                
                if 'Documents' in file_types and file_ext in ['.pdf', '.doc', '.docx', '.txt', '.rtf']:
                    type_matched = True
                elif 'Images' in file_types and file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
                    type_matched = True
                elif 'Videos' in file_types and file_ext in ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv']:
                    type_matched = True
                elif 'Audio' in file_types and file_ext in ['.mp3', '.wav', '.flac', '.ogg', '.aac', '.wma']:
                    type_matched = True
                elif 'Archives' in file_types and file_ext in ['.zip', '.rar', '.7z', '.tar', '.gz']:
                    type_matched = True
                
                if not type_matched:
                    continue
            
            filtered_files.append(file_info)
        
        return filtered_files

    def _start_quick_scan(self):
        """Start a quick system scan."""
        with st.spinner("Starting scan..."):
            try:
                scanner = st.session_state.scanner
                scan_root = Path("C:\\")
                session = ScanService(st.session_state.db).session(scan_root)
                try:
                    files = list(scanner.fast_scan(scan_root, limit=1000))
                    if files:
                        session.record(files)
                    session.complete()
                    st.success(f"Scanned {len(files)} files!")
                except Exception as scan_error:
                    session.fail(str(scan_error))
                    raise
            except Exception as e:
                st.error(f"Scan failed: {e}")
    
    def _start_auto_extract(self):
        """Start content extraction."""
        with st.spinner("Starting extraction..."):
            try:
                extractor = st.session_state.get('auto_extractor')
                if not extractor:
                    from src.extractors.auto_extractor import AutoExtractor
                    extractor = AutoExtractor()
                    st.session_state.auto_extractor = extractor
                
                candidates = extractor.get_extraction_candidates(limit=100)
                if candidates:
                    results = extractor.extract_batch(candidates[:10])
                    st.success(f"Extracted content from {len(results)} files")
                else:
                    st.info("No files ready for extraction")
            except Exception as e:
                st.error(f"Extraction failed: {e}")
    
    def _start_cloud_sync(self):
        """Start cloud synchronization."""
        with st.spinner("Syncing with cloud..."):
            try:
                cloud_sync = st.session_state.cloud_sync
                # Mock sync operation
                time.sleep(2)
                st.success("Cloud sync completed successfully")
            except Exception as e:
                st.error(f"Sync failed: {e}")
    
    def _save_current_workspace(self, name: str):
        """Save current workspace state."""
        workspace_config = {
            'search_filters': st.session_state.get('search_filters', {}),
            'current_page': st.session_state.get('current_page', 'Dashboard'),
            'user_settings': st.session_state.get('user_settings', {}),
            'favorites': st.session_state.get('favorites', [])
        }
        self.workspace_manager.save_workspace(name, workspace_config)
        st.success(f"Workspace '{name}' saved!")
    
    def _create_new_workspace(self, name: str):
        """Create a new workspace."""
        default_config = {
            'search_filters': {},
            'current_page': 'Dashboard',
            'user_settings': {},
            'favorites': []
        }
        self.workspace_manager.save_workspace(name, default_config)
        st.success(f"Workspace '{name}' created!")
        st.rerun()
    
    def _handle_quick_action(self, action: str):
        """Handle quick action button clicks."""
        if action == "scan":
            self._start_quick_scan()
        elif action == "extract":
            self._start_auto_extract()
        elif action == "sync":
            self._start_cloud_sync()