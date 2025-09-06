"""Enhanced UI components with loading states and better feedback."""

import streamlit as st
import time
import threading
from typing import Any, Callable, Optional, Dict, List
from contextlib import contextmanager
import queue

from ..core.monitoring import metrics_collector


class LoadingState:
    """Enhanced loading state management."""
    
    def __init__(self):
        self.active_operations = {}
        self.progress_queues = {}
    
    @contextmanager
    def loading_operation(self, operation_id: str, message: str = "Loading..."):
        """Context manager for loading operations with progress."""
        progress_placeholder = st.empty()
        status_placeholder = st.empty()
        
        try:
            # Show initial loading state
            progress_placeholder.progress(0)
            status_placeholder.info(f"🔄 {message}")
            
            # Setup progress queue
            progress_queue = queue.Queue()
            self.progress_queues[operation_id] = progress_queue
            self.active_operations[operation_id] = True
            
            # Start progress monitor
            monitor_thread = threading.Thread(
                target=self._monitor_progress,
                args=(operation_id, progress_placeholder, status_placeholder),
                daemon=True
            )
            monitor_thread.start()
            
            yield self._create_progress_callback(operation_id)
            
            # Success state
            progress_placeholder.progress(1.0)
            status_placeholder.success("✅ Operation completed successfully!")
            time.sleep(1)  # Brief pause to show success
            
        except Exception as e:
            progress_placeholder.empty()
            status_placeholder.error(f"❌ Operation failed: {str(e)}")
            raise
            
        finally:
            # Cleanup
            self.active_operations.pop(operation_id, None)
            self.progress_queues.pop(operation_id, None)
            
            # Clear UI elements after delay
            time.sleep(2)
            progress_placeholder.empty()
            status_placeholder.empty()
    
    def _create_progress_callback(self, operation_id: str):
        """Create progress callback for the operation."""
        def update_progress(progress: float, message: str = None):
            if operation_id in self.progress_queues:
                self.progress_queues[operation_id].put((progress, message))
        
        return update_progress
    
    def _monitor_progress(self, operation_id: str, progress_placeholder, status_placeholder):
        """Monitor progress updates in background thread."""
        while operation_id in self.active_operations:
            try:
                if operation_id in self.progress_queues:
                    progress, message = self.progress_queues[operation_id].get(timeout=0.1)
                    
                    progress_placeholder.progress(min(progress, 1.0))
                    if message:
                        status_placeholder.info(f"🔄 {message}")
            except queue.Empty:
                continue
            except Exception:
                break


class SmartSearch:
    """Enhanced search component with real-time suggestions."""
    
    def __init__(self, search_func: Callable):
        self.search_func = search_func
        self.loading_state = LoadingState()
    
    def render(self, key: str = "smart_search") -> Optional[List[Dict[str, Any]]]:
        """Render smart search interface."""
        col1, col2, col3 = st.columns([6, 2, 2])
        
        with col1:
            query = st.text_input(
                "Search", 
                placeholder="Type to search files, content, or ask questions...",
                key=f"{key}_input",
                help="🔍 Use natural language: 'Find PDFs about taxes from 2023'"
            )
        
        with col2:
            search_type = st.selectbox(
                "Type",
                ["All", "Semantic", "Text", "Hybrid"],
                key=f"{key}_type"
            )
        
        with col3:
            search_pressed = st.button("🔍 Search", key=f"{key}_button", type="primary")
        
        # Auto-search on Enter or button press
        if query and (search_pressed or st.session_state.get(f"{key}_last_query") != query):
            st.session_state[f"{key}_last_query"] = query
            
            # Track search metrics
            start_time = time.time()
            
            try:
                with self.loading_state.loading_operation(f"search_{key}", f"Searching for: {query}") as progress_callback:
                    # Simulate incremental progress
                    progress_callback(0.2, "Analyzing query...")
                    time.sleep(0.1)
                    
                    progress_callback(0.4, "Searching database...")
                    results = self.search_func(query, search_type)
                    
                    progress_callback(0.8, "Processing results...")
                    time.sleep(0.1)
                    
                    progress_callback(1.0, "Complete!")
                
                # Record metrics
                search_time = time.time() - start_time
                metrics_collector.record_search_request(search_time)
                
                return results
                
            except Exception as e:
                st.error(f"Search failed: {str(e)}")
                metrics_collector.record_error()
                return None
        
        return None


class InteractiveFileTable:
    """Enhanced file table with sorting, filtering, and actions."""
    
    def __init__(self):
        self.loading_state = LoadingState()
    
    def render(self, files: List[Dict[str, Any]], key: str = "file_table") -> Dict[str, Any]:
        """Render interactive file table."""
        if not files:
            st.info("📄 No files found. Try adjusting your search criteria.")
            return {}
        
        # Table controls
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            sort_by = st.selectbox(
                "Sort by",
                ["filename", "size_bytes", "modified_at", "file_type"],
                key=f"{key}_sort"
            )
        
        with col2:
            sort_order = st.selectbox(
                "Order", 
                ["Ascending", "Descending"],
                key=f"{key}_order"
            )
        
        with col3:
            page_size = st.selectbox(
                "Show",
                [10, 25, 50, 100],
                key=f"{key}_page_size",
                index=1
            )
        
        # Sort files
        reverse = sort_order == "Descending"
        sorted_files = sorted(files, key=lambda x: x.get(sort_by, 0), reverse=reverse)
        
        # Pagination
        total_files = len(sorted_files)
        total_pages = (total_files - 1) // page_size + 1
        
        if total_pages > 1:
            page = st.slider(
                f"Page (showing {page_size} of {total_files} files)",
                1, total_pages, 1,
                key=f"{key}_page"
            )
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_files = sorted_files[start_idx:end_idx]
        else:
            page_files = sorted_files[:page_size]
        
        # Bulk actions
        st.markdown("### Bulk Actions")
        bulk_col1, bulk_col2, bulk_col3 = st.columns(3)
        
        with bulk_col1:
            select_all = st.checkbox("Select All", key=f"{key}_select_all")
        
        selected_files = []
        
        # File table
        st.markdown("### Files")
        
        for i, file_info in enumerate(page_files):
            with st.container():
                row_col1, row_col2 = st.columns([1, 10])
                
                with row_col1:
                    selected = st.checkbox(
                        "",
                        value=select_all,
                        key=f"{key}_select_{i}"
                    )
                    if selected:
                        selected_files.append(file_info)
                
                with row_col2:
                    # File info display
                    self._render_file_row(file_info, key, i)
        
        # Bulk action buttons
        if selected_files:
            st.markdown("---")
            bulk_action_col1, bulk_action_col2, bulk_action_col3, bulk_action_col4 = st.columns(4)
            
            with bulk_action_col1:
                if st.button(f"📂 Open Locations ({len(selected_files)})", key=f"{key}_open_bulk"):
                    self._bulk_open_locations(selected_files)
            
            with bulk_action_col2:
                if st.button(f"❤️ Add to Favorites ({len(selected_files)})", key=f"{key}_fav_bulk"):
                    self._bulk_add_favorites(selected_files)
            
            with bulk_action_col3:
                if st.button(f"🏷️ Tag Files ({len(selected_files)})", key=f"{key}_tag_bulk"):
                    st.session_state[f"{key}_show_bulk_tagging"] = True
            
            with bulk_action_col4:
                if st.button(f"📊 Analyze ({len(selected_files)})", key=f"{key}_analyze_bulk"):
                    self._bulk_analyze(selected_files)
        
        # Bulk tagging modal
        if st.session_state.get(f"{key}_show_bulk_tagging"):
            self._render_bulk_tagging_modal(selected_files, key)
        
        return {
            'selected_files': selected_files,
            'total_files': total_files,
            'page_files': page_files
        }
    
    def _render_file_row(self, file_info: Dict[str, Any], key: str, index: int):
        """Render individual file row with rich information."""
        # File icon based on type
        icons = {
            'document': '📄', 'image': '🖼️', 'video': '🎥',
            'audio': '🎵', 'archive': '📦', 'code': '💻',
            'email': '📧', 'other': '📁'
        }
        icon = icons.get(file_info.get('file_type', 'other'), '📁')
        
        # File size formatting
        size_bytes = file_info.get('size_bytes', 0)
        if size_bytes > 1024**3:  # GB
            size_str = f"{size_bytes / (1024**3):.1f} GB"
        elif size_bytes > 1024**2:  # MB
            size_str = f"{size_bytes / (1024**2):.1f} MB"
        elif size_bytes > 1024:  # KB
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes} B"
        
        # Priority indicator
        priority_colors = {
            'critical': '🔴', 'high': '🟠',
            'medium': '🟡', 'low': '🔵'
        }
        priority_icon = priority_colors.get(file_info.get('priority', 'medium'), '🟡')
        
        # Main file information
        col1, col2, col3 = st.columns([6, 2, 2])
        
        with col1:
            st.markdown(f"**{icon} {file_info['filename']}**")
            st.caption(f"📁 {file_info['path']}")
            
            # Show content preview if available
            if file_info.get('content_text'):
                preview = file_info['content_text'][:100]
                if len(file_info['content_text']) > 100:
                    preview += "..."
                st.caption(f"💬 {preview}")
        
        with col2:
            st.text(f"{size_str}")
            st.caption(f"{file_info.get('file_type', 'unknown').title()}")
        
        with col3:
            st.text(f"{priority_icon} {file_info.get('priority', 'medium').title()}")
            
            # Action buttons
            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button("👁️", key=f"{key}_view_{index}", help="Quick view"):
                    self._quick_view_file(file_info)
            with action_col2:
                if st.button("📂", key=f"{key}_open_{index}", help="Open location"):
                    self._open_file_location(file_info)
        
        st.markdown("---")
    
    def _quick_view_file(self, file_info: Dict[str, Any]):
        """Show quick view modal for file."""
        with st.expander(f"👁️ Quick View: {file_info['filename']}", expanded=True):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**File Details:**")
                st.text(f"Type: {file_info.get('file_type', 'unknown')}")
                st.text(f"Size: {file_info.get('size_bytes', 0)} bytes")
                st.text(f"Priority: {file_info.get('priority', 'medium')}")
                
                if file_info.get('modified_at'):
                    st.text(f"Modified: {file_info['modified_at']}")
            
            with col2:
                st.markdown("**Content Preview:**")
                if file_info.get('content_text'):
                    st.text_area("", file_info['content_text'][:500], height=150, disabled=True)
                else:
                    st.info("No text content available")
    
    def _open_file_location(self, file_info: Dict[str, Any]):
        """Open file location in system explorer."""
        import subprocess
        import sys
        from pathlib import Path
        
        try:
            file_path = Path(file_info['path'])
            
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", str(file_path)], check=True)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(file_path)], check=True)
            else:
                subprocess.run(["xdg-open", str(file_path.parent)], check=True)
            
            st.success(f"📂 Opened location for {file_info['filename']}")
            
        except Exception as e:
            st.error(f"Failed to open location: {str(e)}")
    
    def _bulk_open_locations(self, files: List[Dict[str, Any]]):
        """Open multiple file locations."""
        with self.loading_state.loading_operation("bulk_open", "Opening file locations...") as progress:
            for i, file_info in enumerate(files):
                progress((i + 1) / len(files), f"Opening {file_info['filename']}...")
                self._open_file_location(file_info)
                time.sleep(0.1)  # Brief pause between operations
        
        st.success(f"📂 Opened {len(files)} file locations!")
    
    def _bulk_add_favorites(self, files: List[Dict[str, Any]]):
        """Add multiple files to favorites."""
        # This would integrate with the tag manager
        st.success(f"❤️ Added {len(files)} files to favorites!")
    
    def _bulk_analyze(self, files: List[Dict[str, Any]]):
        """Analyze selected files."""
        with st.expander("📊 File Analysis", expanded=True):
            # File type distribution
            file_types = {}
            total_size = 0
            
            for file_info in files:
                file_type = file_info.get('file_type', 'unknown')
                file_types[file_type] = file_types.get(file_type, 0) + 1
                total_size += file_info.get('size_bytes', 0)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**File Types:**")
                for file_type, count in sorted(file_types.items()):
                    st.text(f"{file_type}: {count} files")
            
            with col2:
                st.markdown("**Size Summary:**")
                st.text(f"Total files: {len(files)}")
                st.text(f"Total size: {total_size / (1024**2):.1f} MB")
                st.text(f"Average size: {total_size / len(files) / (1024**2):.1f} MB")
    
    def _render_bulk_tagging_modal(self, files: List[Dict[str, Any]], key: str):
        """Render bulk tagging interface."""
        with st.form(f"{key}_bulk_tagging"):
            st.markdown(f"### 🏷️ Tag {len(files)} Selected Files")
            
            # Tag input
            new_tag = st.text_input("Create new tag")
            
            # Existing tags (would integrate with tag manager)
            existing_tags = st.multiselect(
                "Or select existing tags",
                ["Important", "Legal", "Personal", "Work", "Archive"]
            )
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.form_submit_button("Apply Tags", type="primary"):
                    tags_to_apply = existing_tags.copy()
                    if new_tag:
                        tags_to_apply.append(new_tag)
                    
                    # Apply tags (would integrate with backend)
                    st.success(f"Applied {len(tags_to_apply)} tags to {len(files)} files!")
                    st.session_state[f"{key}_show_bulk_tagging"] = False
            
            with col2:
                if st.form_submit_button("Cancel"):
                    st.session_state[f"{key}_show_bulk_tagging"] = False


class ProgressTracker:
    """Advanced progress tracking with ETA and throughput."""
    
    def __init__(self):
        self.start_time = None
        self.last_update = None
        
    def create_progress_bar(self, total: int, description: str = "Processing"):
        """Create an advanced progress bar."""
        progress_bar = st.progress(0)
        status_text = st.empty()
        stats_text = st.empty()
        
        return AdvancedProgressBar(progress_bar, status_text, stats_text, total, description)


class AdvancedProgressBar:
    """Progress bar with advanced features."""
    
    def __init__(self, progress_bar, status_text, stats_text, total: int, description: str):
        self.progress_bar = progress_bar
        self.status_text = status_text
        self.stats_text = stats_text
        self.total = total
        self.description = description
        self.start_time = time.time()
        self.last_update = self.start_time
        
    def update(self, current: int, message: str = None):
        """Update progress with advanced statistics."""
        now = time.time()
        elapsed = now - self.start_time
        
        # Calculate progress
        progress = current / self.total if self.total > 0 else 0
        self.progress_bar.progress(min(progress, 1.0))
        
        # Calculate statistics
        if elapsed > 0 and current > 0:
            rate = current / elapsed
            eta_seconds = (self.total - current) / rate if rate > 0 else 0
            
            # Format ETA
            if eta_seconds > 3600:
                eta_str = f"{int(eta_seconds // 3600)}h {int((eta_seconds % 3600) // 60)}m"
            elif eta_seconds > 60:
                eta_str = f"{int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
            else:
                eta_str = f"{int(eta_seconds)}s"
            
            # Update displays
            status_msg = message or f"{self.description}..."
            self.status_text.info(f"🔄 {status_msg}")
            
            self.stats_text.caption(
                f"📊 {current:,} / {self.total:,} | "
                f"⚡ {rate:.1f}/sec | "
                f"⏱️ ETA: {eta_str} | "
                f"⏳ Elapsed: {int(elapsed)}s"
            )
        else:
            self.status_text.info(f"🔄 {message or self.description}...")
            self.stats_text.caption(f"📊 {current:,} / {self.total:,}")
    
    def complete(self, message: str = "Completed!"):
        """Mark progress as complete."""
        self.progress_bar.progress(1.0)
        self.status_text.success(f"✅ {message}")
        
        elapsed = time.time() - self.start_time
        final_rate = self.total / elapsed if elapsed > 0 else 0
        
        self.stats_text.success(
            f"🎉 Processed {self.total:,} items in {int(elapsed)}s "
            f"(avg {final_rate:.1f}/sec)"
        )


# Global instances
loading_state = LoadingState()
progress_tracker = ProgressTracker()