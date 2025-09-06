"""Interactive table component with sorting, filtering, and advanced features."""

import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import math


class InteractiveTable:
    """Advanced interactive table for search results with sorting and filtering."""
    
    def __init__(self, key_prefix: str = "table"):
        self.key_prefix = key_prefix
        
    def render(
        self,
        data: List[Dict[str, Any]],
        title: str = "Search Results",
        page_size: int = 20,
        show_actions: bool = True,
        show_export: bool = True
    ):
        """
        Render an interactive table with advanced features.
        
        Args:
            data: List of dictionaries containing the data
            title: Title for the table
            page_size: Number of rows per page
            show_actions: Show action buttons for each row
            show_export: Show export options
        """
        
        if not data:
            st.info("📭 No results found")
            return None
        
        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(data)
        
        # Header with title and stats
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.subheader(f"{title} ({len(df):,} results)")
        with col2:
            if show_export:
                if st.button("📥 Export CSV", key=f"{self.key_prefix}_export"):
                    self._export_csv(df)
        with col3:
            if st.button("🔄 Refresh", key=f"{self.key_prefix}_refresh"):
                st.rerun()
        
        # Filtering Section
        with st.expander("🔍 **Advanced Filters & Sorting**", expanded=True):
            filter_cols = st.columns(4)
            
            # Column selection for display
            with filter_cols[0]:
                available_columns = list(df.columns)
                default_columns = self._get_default_columns(available_columns)
                selected_columns = st.multiselect(
                    "📋 Display Columns",
                    available_columns,
                    default=default_columns,
                    key=f"{self.key_prefix}_columns"
                )
            
            # Sorting options
            with filter_cols[1]:
                sort_column = st.selectbox(
                    "🔼 Sort By",
                    selected_columns if selected_columns else available_columns,
                    key=f"{self.key_prefix}_sort_col"
                )
                sort_order = st.radio(
                    "Order",
                    ["Ascending ↑", "Descending ↓"],
                    key=f"{self.key_prefix}_sort_order",
                    horizontal=True
                )
            
            # Text filter
            with filter_cols[2]:
                text_filter = st.text_input(
                    "🔎 Text Filter",
                    placeholder="Filter results...",
                    key=f"{self.key_prefix}_text_filter"
                )
            
            # File type filter
            with filter_cols[3]:
                if 'extension' in df.columns:
                    unique_extensions = df['extension'].dropna().unique()
                    selected_extensions = st.multiselect(
                        "📄 File Types",
                        unique_extensions,
                        key=f"{self.key_prefix}_ext_filter"
                    )
                else:
                    selected_extensions = []
            
            # Size filter
            size_cols = st.columns(3)
            with size_cols[0]:
                if 'size_bytes' in df.columns:
                    min_size_mb = st.number_input(
                        "Min Size (MB)",
                        min_value=0.0,
                        value=0.0,
                        step=1.0,
                        key=f"{self.key_prefix}_min_size"
                    )
                else:
                    min_size_mb = 0
            
            with size_cols[1]:
                if 'size_bytes' in df.columns:
                    max_size_mb = st.number_input(
                        "Max Size (MB)",
                        min_value=0.0,
                        value=0.0,
                        step=10.0,
                        key=f"{self.key_prefix}_max_size",
                        help="0 = No limit"
                    )
                else:
                    max_size_mb = 0
            
            # Date filter
            with size_cols[2]:
                if 'modified_at' in df.columns:
                    date_range = st.date_input(
                        "📅 Date Range",
                        value=[],
                        key=f"{self.key_prefix}_date_range",
                        help="Select start and end date"
                    )
                else:
                    date_range = []
        
        # Apply filters
        filtered_df = self._apply_filters(
            df,
            text_filter,
            selected_extensions,
            min_size_mb,
            max_size_mb,
            date_range
        )
        
        # Apply sorting
        if sort_column and sort_column in filtered_df.columns:
            ascending = "Ascending" in sort_order
            filtered_df = filtered_df.sort_values(by=sort_column, ascending=ascending)
        
        # Select only chosen columns
        if selected_columns:
            display_df = filtered_df[selected_columns].copy()
        else:
            display_df = filtered_df.copy()
        
        # Statistics bar
        self._render_statistics(filtered_df, len(df))
        
        # Pagination
        total_pages = math.ceil(len(display_df) / page_size)
        
        if total_pages > 1:
            page_cols = st.columns([1, 3, 1])
            with page_cols[1]:
                current_page = st.slider(
                    "Page",
                    1,
                    total_pages,
                    1,
                    key=f"{self.key_prefix}_page"
                )
        else:
            current_page = 1
        
        # Calculate page boundaries
        start_idx = (current_page - 1) * page_size
        end_idx = min(start_idx + page_size, len(display_df))
        
        # Display current page data
        page_df = display_df.iloc[start_idx:end_idx]
        
        # Format the dataframe for better display
        formatted_df = self._format_dataframe(page_df)
        
        # Render as interactive table with checkboxes
        if show_actions:
            self._render_with_actions(formatted_df, filtered_df.iloc[start_idx:end_idx])
        else:
            # Use Streamlit's native dataframe with enhanced styling
            st.dataframe(
                formatted_df,
                use_container_width=True,
                hide_index=True,
                column_config=self._get_column_config()
            )
        
        # Page info
        if total_pages > 1:
            st.caption(f"📄 Page {current_page} of {total_pages} | Showing {start_idx+1}-{end_idx} of {len(filtered_df)} filtered results")
        
        # Return selected items if any
        return st.session_state.get(f"{self.key_prefix}_selected", [])
    
    def _get_default_columns(self, available: List[str]) -> List[str]:
        """Get default columns to display."""
        priority_columns = [
            'filename', 'path', 'size_bytes', 'extension',
            'modified_at', 'file_type', 'priority'
        ]
        return [col for col in priority_columns if col in available]
    
    def _apply_filters(
        self,
        df: pd.DataFrame,
        text_filter: str,
        extensions: List[str],
        min_size_mb: float,
        max_size_mb: float,
        date_range: List
    ) -> pd.DataFrame:
        """Apply all filters to the dataframe."""
        filtered = df.copy()
        
        # Text filter
        if text_filter:
            text_lower = text_filter.lower()
            text_columns = ['filename', 'path', 'content_text']
            mask = pd.Series([False] * len(filtered))
            for col in text_columns:
                if col in filtered.columns:
                    mask |= filtered[col].astype(str).str.lower().str.contains(text_lower, na=False)
            filtered = filtered[mask]
        
        # Extension filter
        if extensions and 'extension' in filtered.columns:
            filtered = filtered[filtered['extension'].isin(extensions)]
        
        # Size filter
        if 'size_bytes' in filtered.columns:
            if min_size_mb > 0:
                filtered = filtered[filtered['size_bytes'] >= (min_size_mb * 1024 * 1024)]
            if max_size_mb > 0:
                filtered = filtered[filtered['size_bytes'] <= (max_size_mb * 1024 * 1024)]
        
        # Date filter
        if date_range and len(date_range) == 2 and 'modified_at' in filtered.columns:
            start_date, end_date = date_range
            filtered['modified_date'] = pd.to_datetime(filtered['modified_at'], errors='coerce')
            mask = (filtered['modified_date'].dt.date >= start_date) & \
                   (filtered['modified_date'].dt.date <= end_date)
            filtered = filtered[mask]
            filtered = filtered.drop('modified_date', axis=1)
        
        return filtered
    
    def _format_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Format dataframe for better display."""
        formatted = df.copy()
        
        # Format file sizes
        if 'size_bytes' in formatted.columns:
            formatted['size'] = formatted['size_bytes'].apply(self._format_size)
            formatted = formatted.drop('size_bytes', axis=1)
        
        # Format dates
        for col in ['modified_at', 'created_at']:
            if col in formatted.columns:
                formatted[col] = pd.to_datetime(formatted[col], errors='coerce').dt.strftime('%Y-%m-%d %H:%M')
        
        # Truncate long paths
        if 'path' in formatted.columns:
            formatted['path'] = formatted['path'].apply(lambda x: self._truncate_path(x))
        
        # Truncate long filenames
        if 'filename' in formatted.columns:
            formatted['filename'] = formatted['filename'].apply(
                lambda x: x[:50] + '...' if len(str(x)) > 50 else x
            )
        
        return formatted
    
    def _format_size(self, size_bytes: float) -> str:
        """Format file size in human-readable format."""
        if pd.isna(size_bytes):
            return "N/A"
        
        size_bytes = float(size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
    
    def _truncate_path(self, path: str, max_length: int = 60) -> str:
        """Truncate long paths intelligently."""
        if not path or len(path) <= max_length:
            return path
        
        path_obj = Path(path)
        parts = path_obj.parts
        
        if len(parts) <= 3:
            return path[:max_length-3] + "..."
        
        # Keep drive and filename, truncate middle
        return f"{parts[0]}\\...\\{parts[-2]}\\{parts[-1]}"
    
    def _get_column_config(self) -> Dict:
        """Get column configuration for st.dataframe."""
        return {
            "size": st.column_config.TextColumn("Size", width="small"),
            "extension": st.column_config.TextColumn("Type", width="small"),
            "modified_at": st.column_config.TextColumn("Modified", width="medium"),
            "filename": st.column_config.TextColumn("Filename", width="large"),
            "path": st.column_config.TextColumn("Path", width="large"),
        }
    
    def _render_with_actions(self, display_df: pd.DataFrame, full_df: pd.DataFrame):
        """Render table with action buttons."""
        
        # Initialize selected items in session state
        if f"{self.key_prefix}_selected" not in st.session_state:
            st.session_state[f"{self.key_prefix}_selected"] = []
        
        # Select all/none buttons
        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            if st.button("☑️ Select All", key=f"{self.key_prefix}_select_all"):
                st.session_state[f"{self.key_prefix}_selected"] = full_df.to_dict('records')
        with col2:
            if st.button("☐ Clear All", key=f"{self.key_prefix}_clear_all"):
                st.session_state[f"{self.key_prefix}_selected"] = []
        with col3:
            selected_count = len(st.session_state[f"{self.key_prefix}_selected"])
            if selected_count > 0:
                st.success(f"✅ {selected_count} items selected")
        
        # Render table with checkboxes
        for idx, (display_row, full_row) in enumerate(zip(display_df.itertuples(), full_df.itertuples())):
            cols = st.columns([0.5, 3, 1, 1, 1])
            
            # Checkbox
            with cols[0]:
                is_selected = any(
                    item.get('id') == getattr(full_row, 'id', idx)
                    for item in st.session_state[f"{self.key_prefix}_selected"]
                )
                
                if st.checkbox("", value=is_selected, key=f"{self.key_prefix}_cb_{idx}"):
                    # Add to selected
                    item = full_df.iloc[idx].to_dict()
                    if not any(s.get('id') == item.get('id') for s in st.session_state[f"{self.key_prefix}_selected"]):
                        st.session_state[f"{self.key_prefix}_selected"].append(item)
                else:
                    # Remove from selected
                    st.session_state[f"{self.key_prefix}_selected"] = [
                        s for s in st.session_state[f"{self.key_prefix}_selected"]
                        if s.get('id') != full_df.iloc[idx].to_dict().get('id')
                    ]
            
            # Main content
            with cols[1]:
                # Show filename with icon
                filename = getattr(display_row, 'filename', 'Unknown')
                extension = getattr(full_row, 'extension', '').lower()
                icon = self._get_file_icon(extension)
                st.markdown(f"{icon} **{filename}**")
                
                # Show path in smaller text
                if hasattr(display_row, 'path'):
                    st.caption(getattr(display_row, 'path', ''))
            
            # Size
            with cols[2]:
                if hasattr(display_row, 'size'):
                    st.text(getattr(display_row, 'size', 'N/A'))
            
            # Date
            with cols[3]:
                if hasattr(display_row, 'modified_at'):
                    st.text(getattr(display_row, 'modified_at', 'N/A'))
            
            # Actions
            with cols[4]:
                action_cols = st.columns(2)
                with action_cols[0]:
                    if st.button("👁️", key=f"{self.key_prefix}_view_{idx}", help="View details"):
                        st.session_state[f"{self.key_prefix}_view"] = full_df.iloc[idx].to_dict()
                with action_cols[1]:
                    if st.button("📂", key=f"{self.key_prefix}_open_{idx}", help="Open location"):
                        path = getattr(full_row, 'path', '')
                        if path:
                            import subprocess
                            import os
                            folder = os.path.dirname(path)
                            subprocess.Popen(f'explorer "{folder}"')
            
            st.divider()
    
    def _get_file_icon(self, extension: str) -> str:
        """Get emoji icon for file type."""
        icons = {
            '.pdf': '📑',
            '.doc': '📝', '.docx': '📝',
            '.xls': '📊', '.xlsx': '📊',
            '.ppt': '📽️', '.pptx': '📽️',
            '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️',
            '.mp4': '🎥', '.avi': '🎥', '.mov': '🎥',
            '.mp3': '🎵', '.wav': '🎵',
            '.zip': '📦', '.rar': '📦', '.7z': '📦',
            '.txt': '📄', '.rtf': '📄',
            '.msg': '📧', '.eml': '📧',
            '.exe': '⚙️', '.msi': '⚙️',
            '.py': '🐍', '.js': '📜', '.html': '🌐',
        }
        return icons.get(extension, '📄')
    
    def _render_statistics(self, filtered_df: pd.DataFrame, total_count: int):
        """Render statistics bar."""
        cols = st.columns(4)
        
        with cols[0]:
            st.metric("Filtered", f"{len(filtered_df):,}", f"{len(filtered_df)/total_count*100:.1f}%")
        
        with cols[1]:
            if 'size_bytes' in filtered_df.columns:
                total_size = filtered_df['size_bytes'].sum()
                st.metric("Total Size", self._format_size(total_size))
        
        with cols[2]:
            if 'extension' in filtered_df.columns:
                unique_types = filtered_df['extension'].nunique()
                st.metric("File Types", unique_types)
        
        with cols[3]:
            if 'modified_at' in filtered_df.columns:
                latest = pd.to_datetime(filtered_df['modified_at'], errors='coerce').max()
                if pd.notna(latest):
                    st.metric("Latest", latest.strftime('%Y-%m-%d'))
    
    def _export_csv(self, df: pd.DataFrame):
        """Export dataframe to CSV."""
        csv = df.to_csv(index=False)
        st.download_button(
            label="💾 Download CSV",
            data=csv,
            file_name=f"search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key=f"{self.key_prefix}_download"
        )