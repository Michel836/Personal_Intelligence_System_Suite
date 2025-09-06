"""Real-time activity monitor component for 36TB Intelligence."""

import streamlit as st
import time
from datetime import datetime
from typing import Dict, Any, Optional
import threading


class ActivityMonitor:
    """Real-time system activity monitor for sidebar."""
    
    def __init__(self, db_manager, scanner, chat_engine, tag_manager):
        self.db = db_manager
        self.scanner = scanner
        self.chat_engine = chat_engine
        self.tag_manager = tag_manager
        self.last_update = datetime.now()
    
    def render(self):
        """Render the activity monitor in the sidebar."""
        
        # Main container with custom styling
        st.markdown("""
        <style>
        .activity-monitor {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 10px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .activity-item {
            background: rgba(255,255,255,0.1);
            padding: 5px;
            margin: 5px 0;
            border-radius: 5px;
        }
        .pulse {
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Get current stats with error handling
        try:
            stats = self.db.get_stats()
        except Exception as e:
            st.error(f"Database temporarily unavailable: {e}")
            stats = {
                'total_files': 0,
                'total_gb': 0.0,
                'by_type': {},
                'scan_duration': 0.0
            }
        
        # Main metrics
        col1, col2 = st.columns(2)
        with col1:
            st.metric(
                "📁 Files", 
                f"{stats.get('total_files', 0):,}",
                delta=None,
                help="Total indexed files"
            )
        with col2:
            gb_size = stats.get('total_gb', 0)
            st.metric(
                "💾 Size", 
                f"{gb_size:.1f} GB",
                delta=None,
                help="Total data size"
            )
        
        # Scanner Status with animated indicator
        st.markdown("### 🔍 Scanner")
        if self.scanner and hasattr(self.scanner, 'is_running') and self.scanner.is_running:
            # Animated scanning indicator
            st.markdown("""
            <div style="display: flex; align-items: center;">
                <div class="pulse" style="width: 10px; height: 10px; background: #00ff00; border-radius: 50%; margin-right: 10px;"></div>
                <span style="color: #00ff00; font-weight: bold;">SCANNING</span>
            </div>
            """, unsafe_allow_html=True)
            
            # Progress details
            if hasattr(self.scanner, 'progress'):
                progress = self.scanner.progress
                if progress.scanned_files > 0:
                    # Progress bar
                    progress_pct = min(progress.scanned_files / 100000, 1.0)
                    st.progress(progress_pct, text=f"{progress.scanned_files:,} files")
                    
                    # Speed indicator
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption(f"⚡ {progress.files_per_second:.0f} files/s")
                    with col2:
                        if progress.current_file:
                            current = progress.current_file.split('\\')[-1][:15]
                            st.caption(f"📍 {current}...")
        else:
            st.markdown("""
            <div style="display: flex; align-items: center;">
                <div style="width: 10px; height: 10px; background: #3498db; border-radius: 50%; margin-right: 10px;"></div>
                <span style="color: #3498db;">Ready to scan</span>
            </div>
            """, unsafe_allow_html=True)
        
        # AI Status
        st.markdown("### 🤖 AI Engine")
        try:
            if self.chat_engine and hasattr(self.chat_engine, 'is_available') and self.chat_engine.is_available():
                st.markdown("""
                <div style="display: flex; align-items: center;">
                    <div style="width: 10px; height: 10px; background: #00ff00; border-radius: 50%; margin-right: 10px;"></div>
                    <span style="color: #00ff00; font-weight: bold;">ONLINE</span>
                </div>
                """, unsafe_allow_html=True)
                st.caption("🦙 llama3.2 ready")
            else:
                st.markdown("""
                <div style="display: flex; align-items: center;">
                    <div style="width: 10px; height: 10px; background: #ffa500; border-radius: 50%; margin-right: 10px;"></div>
                    <span style="color: #ffa500;">OFFLINE</span>
                </div>
                """, unsafe_allow_html=True)
        except:
            st.markdown("""
            <div style="display: flex; align-items: center;">
                <div style="width: 10px; height: 10px; background: #ff0000; border-radius: 50%; margin-right: 10px;"></div>
                <span style="color: #ff0000;">ERROR</span>
            </div>
            """, unsafe_allow_html=True)
        
        # File Type Distribution (mini chart)
        st.markdown("### 📊 File Types")
        if 'by_type' in stats:
            for file_type, count in list(stats['by_type'].items())[:5]:
                # Mini bar chart
                pct = (count / stats['total_files']) * 100 if stats['total_files'] > 0 else 0
                st.progress(pct / 100, text=f"{file_type}: {count:,}")
        
        # Recent Activity
        st.markdown("### 🕐 Recent Activity")
        recent = self.db.get_recent_files(3)
        if recent:
            for file in recent:
                filename = file['filename']
                if len(filename) > 25:
                    filename = filename[:22] + "..."
                
                # File type emoji
                ext = file.get('extension', '').lower()
                if ext in ['.pdf']:
                    emoji = "📑"
                elif ext in ['.doc', '.docx']:
                    emoji = "📝"
                elif ext in ['.jpg', '.png', '.jpeg']:
                    emoji = "🖼️"
                elif ext in ['.mp4', '.avi', '.mov']:
                    emoji = "🎥"
                elif ext in ['.zip', '.rar', '.7z']:
                    emoji = "📦"
                else:
                    emoji = "📄"
                
                st.caption(f"{emoji} {filename}")
        else:
            st.caption("No recent files")
        
        # Quick Actions
        st.markdown("### ⚡ Quick Actions")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔍 Search", use_container_width=True, key="quick_search"):
                st.session_state.selected_page = "🔍 Search"
        with col2:
            if st.button("🚀 Scan", use_container_width=True, key="quick_scan"):
                st.session_state.selected_page = "🚀 Scanner"
        
        # Last update time
        st.caption(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
        
        # Auto-refresh hint
        st.caption("💡 Auto-refreshes with page interactions")


def render_activity_monitor(db, scanner, chat_engine, tag_manager):
    """Helper function to render activity monitor."""
    monitor = ActivityMonitor(db, scanner, chat_engine, tag_manager)
    monitor.render()