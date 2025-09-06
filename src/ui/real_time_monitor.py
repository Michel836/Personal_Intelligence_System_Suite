"""Real-time activity monitor with visual indicators for all functions."""

import streamlit as st
import time
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
import psutil
import json
from pathlib import Path
import queue
from dataclasses import dataclass, asdict
from enum import Enum

class ActivityType(Enum):
    """Types of activities to monitor."""
    SCAN = "scan"
    SEARCH = "search"
    AI_CHAT = "ai_chat"
    DATABASE = "database"
    FILE_PROCESSING = "file_processing"
    EXTRACTION = "extraction"
    INDEXING = "indexing"
    UI_INTERACTION = "ui_interaction"
    SYSTEM = "system"
    STARTUP = "startup"

class ActivityStatus(Enum):
    """Activity status levels."""
    IDLE = "idle"
    WORKING = "working"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"

@dataclass
class Activity:
    """Activity data structure."""
    id: str
    type: ActivityType
    status: ActivityStatus
    message: str
    timestamp: datetime
    progress: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
    duration: Optional[float] = None

class RealTimeActivityMonitor:
    """Global real-time activity monitor singleton."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.activities: Dict[str, Activity] = {}
        self.activity_queue = queue.Queue()
        self.max_activities = 100
        self.is_running = True
        self._initialized = True
        
        # Start background monitoring
        self._start_system_monitoring()
    
    def add_activity(self, activity_type: ActivityType, message: str, 
                    activity_id: Optional[str] = None, progress: Optional[float] = None,
                    details: Optional[Dict[str, Any]] = None) -> str:
        """Add or update an activity."""
        if activity_id is None:
            activity_id = f"{activity_type.value}_{int(time.time() * 1000)}"
        
        activity = Activity(
            id=activity_id,
            type=activity_type,
            status=ActivityStatus.WORKING,
            message=message,
            timestamp=datetime.now(),
            progress=progress,
            details=details or {}
        )
        
        with self._lock:
            self.activities[activity_id] = activity
            self._cleanup_old_activities()
        
        # Add to queue for real-time updates
        try:
            self.activity_queue.put(activity, block=False)
        except queue.Full:
            pass
        
        return activity_id
    
    def update_activity(self, activity_id: str, status: Optional[ActivityStatus] = None,
                       message: Optional[str] = None, progress: Optional[float] = None,
                       details: Optional[Dict[str, Any]] = None):
        """Update an existing activity."""
        with self._lock:
            if activity_id in self.activities:
                activity = self.activities[activity_id]
                if status is not None:
                    activity.status = status
                if message is not None:
                    activity.message = message
                if progress is not None:
                    activity.progress = progress
                if details is not None:
                    activity.details.update(details)
                
                activity.timestamp = datetime.now()
                
                # Calculate duration if completed
                if status in [ActivityStatus.SUCCESS, ActivityStatus.ERROR]:
                    if 'start_time' in activity.details:
                        activity.duration = time.time() - activity.details['start_time']
    
    def complete_activity(self, activity_id: str, success: bool = True, message: Optional[str] = None):
        """Mark activity as completed."""
        status = ActivityStatus.SUCCESS if success else ActivityStatus.ERROR
        self.update_activity(activity_id, status=status, message=message)
    
    def get_active_activities(self) -> List[Activity]:
        """Get all currently active activities."""
        with self._lock:
            return [a for a in self.activities.values() if a.status == ActivityStatus.WORKING]
    
    def get_recent_activities(self, limit: int = 10) -> List[Activity]:
        """Get recent activities."""
        with self._lock:
            activities = sorted(self.activities.values(), key=lambda x: x.timestamp, reverse=True)
            return activities[:limit]
    
    def get_activity_stats(self) -> Dict[str, Any]:
        """Get activity statistics."""
        with self._lock:
            stats = {
                'total_activities': len(self.activities),
                'active_count': len([a for a in self.activities.values() if a.status == ActivityStatus.WORKING]),
                'success_count': len([a for a in self.activities.values() if a.status == ActivityStatus.SUCCESS]),
                'error_count': len([a for a in self.activities.values() if a.status == ActivityStatus.ERROR]),
                'by_type': {}
            }
            
            for activity in self.activities.values():
                type_name = activity.type.value
                if type_name not in stats['by_type']:
                    stats['by_type'][type_name] = 0
                stats['by_type'][type_name] += 1
            
            return stats
    
    def _cleanup_old_activities(self):
        """Remove old activities to prevent memory bloat."""
        if len(self.activities) <= self.max_activities:
            return
        
        # Keep only the most recent activities
        sorted_activities = sorted(self.activities.items(), key=lambda x: x[1].timestamp, reverse=True)
        self.activities = dict(sorted_activities[:self.max_activities])
    
    def _start_system_monitoring(self):
        """Start background system monitoring."""
        def monitor_system():
            while self.is_running:
                try:
                    # Monitor CPU and memory
                    cpu_percent = psutil.cpu_percent(interval=1)
                    memory = psutil.virtual_memory()
                    
                    # Add system activity if resources are high
                    if cpu_percent > 80:
                        self.add_activity(
                            ActivityType.SYSTEM,
                            f"High CPU usage: {cpu_percent:.1f}%",
                            "system_cpu",
                            details={'cpu_percent': cpu_percent}
                        )
                        self.complete_activity("system_cpu", success=True)
                    
                    if memory.percent > 85:
                        self.add_activity(
                            ActivityType.SYSTEM,
                            f"High memory usage: {memory.percent:.1f}%",
                            "system_memory",
                            details={'memory_percent': memory.percent}
                        )
                        self.complete_activity("system_memory", success=True)
                    
                    time.sleep(5)  # Check every 5 seconds
                    
                except Exception as e:
                    time.sleep(10)  # Wait longer on error
        
        thread = threading.Thread(target=monitor_system, daemon=True)
        thread.start()
    
    def stop(self):
        """Stop the activity monitor."""
        self.is_running = False

# Global instance
rt_monitor = RealTimeActivityMonitor()

def render_floating_activity_indicator():
    """Render floating activity indicator at top-right of screen."""
    active_activities = rt_monitor.get_active_activities()
    
    if active_activities:
        # CSS for floating indicator
        st.markdown("""
        <style>
        .floating-activity {
            position: fixed;
            top: 10px;
            right: 10px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 8px 12px;
            border-radius: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 9999;
            font-size: 12px;
            font-weight: bold;
            animation: pulse-glow 2s infinite;
            min-width: 120px;
            text-align: center;
        }
        
        @keyframes pulse-glow {
            0%, 100% { 
                transform: scale(1); 
                box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
            }
            50% { 
                transform: scale(1.05); 
                box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
            }
        }
        
        .activity-dot {
            display: inline-block;
            width: 6px;
            height: 6px;
            background: #fff;
            border-radius: 50%;
            margin-right: 6px;
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0%, 50% { opacity: 1; }
            51%, 100% { opacity: 0.3; }
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Count active processes
        active_count = len(active_activities)
        
        # Show different message based on activity type
        main_activity = active_activities[0]
        activity_icons = {
            ActivityType.SCAN: "🔍",
            ActivityType.SEARCH: "🔎", 
            ActivityType.AI_CHAT: "🤖",
            ActivityType.DATABASE: "🗄️",
            ActivityType.FILE_PROCESSING: "📄",
            ActivityType.EXTRACTION: "📤",
            ActivityType.INDEXING: "📇",
            ActivityType.UI_INTERACTION: "🖱️",
            ActivityType.SYSTEM: "⚙️",
            ActivityType.STARTUP: "🚀"
        }
        
        icon = activity_icons.get(main_activity.type, "🔄")
        
        if active_count == 1:
            display_text = f"{icon} {main_activity.type.value.title()}"
        else:
            display_text = f"{icon} {active_count} processes"
        
        # Floating indicator
        st.markdown(f"""
        <div class="floating-activity">
            <span class="activity-dot"></span>
            {display_text}
        </div>
        """, unsafe_allow_html=True)

def render_sidebar_activity_monitor():
    """Render compact activity monitor for sidebar."""
    st.markdown("### 🔄 Live Activity")
    
    # Quick stats
    stats = rt_monitor.get_activity_stats()
    active_count = stats['active_count']
    
    # Status indicator
    if active_count > 0:
        st.markdown(f"""
        <div style="display: flex; align-items: center; margin-bottom: 10px;">
            <div style="width: 8px; height: 8px; background: #00ff00; border-radius: 50%; margin-right: 8px; animation: pulse 1s infinite;"></div>
            <span style="color: #00ff00; font-weight: bold;">ACTIVE ({active_count})</span>
        </div>
        """, unsafe_allow_html=True)
        
        # Show active activities (max 3)
        active_activities = rt_monitor.get_active_activities()
        for activity in active_activities[:3]:
            progress_text = ""
            if activity.progress is not None:
                progress_text = f" ({activity.progress:.0f}%)"
                st.progress(activity.progress / 100.0)
            
            # Activity type icons
            activity_icons = {
                ActivityType.SCAN: "🔍",
                ActivityType.SEARCH: "🔎", 
                ActivityType.AI_CHAT: "🤖",
                ActivityType.DATABASE: "🗄️",
                ActivityType.FILE_PROCESSING: "📄",
                ActivityType.EXTRACTION: "📤",
                ActivityType.INDEXING: "📇",
                ActivityType.UI_INTERACTION: "🖱️",
                ActivityType.SYSTEM: "⚙️",
                ActivityType.STARTUP: "🚀"
            }
            
            icon = activity_icons.get(activity.type, "🔄")
            
            st.markdown(f"**{icon} {activity.message}**{progress_text}")
    else:
        st.markdown(f"""
        <div style="display: flex; align-items: center; margin-bottom: 10px;">
            <div style="width: 8px; height: 8px; background: #3498db; border-radius: 50%; margin-right: 8px;"></div>
            <span style="color: #3498db;">IDLE</span>
        </div>
        """, unsafe_allow_html=True)
    
    # Recent activity (last 3)
    st.markdown("**Recent:**")
    recent = rt_monitor.get_recent_activities(3)
    for activity in recent:
        status_colors = {
            ActivityStatus.SUCCESS: "🟢",
            ActivityStatus.ERROR: "🔴",
            ActivityStatus.WARNING: "🟡", 
            ActivityStatus.WORKING: "🔵",
            ActivityStatus.IDLE: "⚪"
        }
        
        color = status_colors.get(activity.status, "⚪")
        timestamp = activity.timestamp.strftime("%H:%M:%S")
        
        # Truncate message if too long
        message = activity.message
        if len(message) > 25:
            message = message[:22] + "..."
        
        st.caption(f"{color} {timestamp} {message}")
    
    # System stats
    st.markdown("**System:**")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("CPU", f"{psutil.cpu_percent():.0f}%", delta=None)
    with col2:
        memory = psutil.virtual_memory()
        st.metric("RAM", f"{memory.percent:.0f}%", delta=None)

def render_full_activity_dashboard():
    """Render full activity dashboard for main interface."""
    st.markdown("## 🔄 Real-Time Activity Dashboard")
    
    # Stats row
    col1, col2, col3, col4 = st.columns(4)
    stats = rt_monitor.get_activity_stats()
    
    with col1:
        st.metric("🔄 Active", stats['active_count'])
    with col2:
        st.metric("✅ Completed", stats['success_count'])
    with col3:
        st.metric("❌ Errors", stats['error_count'])
    with col4:
        st.metric("📊 Total", stats['total_activities'])
    
    # Active processes section
    st.markdown("### 🟡 Active Processes")
    
    active_activities = rt_monitor.get_active_activities()
    if active_activities:
        for activity in active_activities:
            with st.container():
                col1, col2 = st.columns([4, 1])
                
                with col1:
                    # Activity details
                    st.markdown(f"**{activity.type.value.title()}**: {activity.message}")
                    
                    # Progress bar if available
                    if activity.progress is not None:
                        st.progress(activity.progress / 100.0, text=f"{activity.progress:.1f}%")
                    
                    # Duration
                    elapsed = (datetime.now() - activity.timestamp).total_seconds()
                    st.caption(f"⏱️ Running for {elapsed:.0f}s")
                
                with col2:
                    # Activity type icon
                    activity_icons = {
                        ActivityType.SCAN: "🔍",
                        ActivityType.SEARCH: "🔎", 
                        ActivityType.AI_CHAT: "🤖",
                        ActivityType.DATABASE: "🗄️",
                        ActivityType.FILE_PROCESSING: "📄",
                        ActivityType.EXTRACTION: "📤",
                        ActivityType.INDEXING: "📇",
                        ActivityType.UI_INTERACTION: "🖱️",
                        ActivityType.SYSTEM: "⚙️",
                        ActivityType.STARTUP: "🚀"
                    }
                    
                    icon = activity_icons.get(activity.type, "🔄")
                    st.markdown(f"<div style='font-size: 2em; text-align: center;'>{icon}</div>", 
                              unsafe_allow_html=True)
                
                st.divider()
    else:
        st.info("🟢 No active processes. System is idle.")
    
    # Activity log
    st.markdown("### 📋 Activity Log")
    
    recent_activities = rt_monitor.get_recent_activities(15)
    if recent_activities:
        # Create scrollable container
        with st.container(height=300):
            for activity in recent_activities:
                status_colors = {
                    ActivityStatus.SUCCESS: "🟢",
                    ActivityStatus.ERROR: "🔴",
                    ActivityStatus.WARNING: "🟡", 
                    ActivityStatus.WORKING: "🔵",
                    ActivityStatus.IDLE: "⚪"
                }
                
                color = status_colors.get(activity.status, "⚪")
                timestamp_str = activity.timestamp.strftime("%H:%M:%S")
                
                duration_str = ""
                if activity.duration and activity.duration > 0:
                    duration_str = f" ({activity.duration:.1f}s)"
                
                st.markdown(f"{color} **{timestamp_str}** [{activity.type.value}] {activity.message}{duration_str}")
    else:
        st.info("No activity to display.")

# Helper functions for easy integration

def start_activity(activity_type: ActivityType, message: str, **kwargs) -> str:
    """Start tracking an activity."""
    details = kwargs.copy()
    details['start_time'] = time.time()
    return rt_monitor.add_activity(activity_type, message, details=details)

def update_progress(activity_id: str, progress: float, message: Optional[str] = None):
    """Update activity progress."""
    rt_monitor.update_activity(activity_id, progress=progress, message=message)

def finish_activity(activity_id: str, success: bool = True, message: Optional[str] = None):
    """Finish an activity."""
    rt_monitor.complete_activity(activity_id, success=success, message=message)

# Context manager for easy activity tracking
class ActivityTracker:
    """Context manager for automatic activity tracking."""
    
    def __init__(self, activity_type: ActivityType, message: str, **kwargs):
        self.activity_type = activity_type
        self.message = message
        self.kwargs = kwargs
        self.activity_id = None
    
    def __enter__(self):
        self.activity_id = start_activity(self.activity_type, self.message, **self.kwargs)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.activity_id:
            success = exc_type is None
            error_msg = str(exc_val) if exc_val else None
            finish_activity(self.activity_id, success=success, message=error_msg)
    
    def update(self, progress: float, message: Optional[str] = None):
        """Update progress within the context."""
        if self.activity_id:
            update_progress(self.activity_id, progress, message)

# Decorator for automatic function tracking
def track_activity(activity_type: ActivityType, message: str):
    """Decorator to automatically track function execution."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with ActivityTracker(activity_type, message):
                return func(*args, **kwargs)
        return wrapper
    return decorator