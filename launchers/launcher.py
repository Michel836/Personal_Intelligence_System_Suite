"""Launcher for 36TB Intelligence - Choose your interface experience."""

import streamlit as st
import subprocess
import sys
from pathlib import Path
import time
import os

# Import real-time activity monitor
from src.ui.real_time_monitor import (
    render_floating_activity_indicator,
    render_sidebar_activity_monitor,
    start_activity,
    finish_activity,
    ActivityType,
    rt_monitor
)

# Page config
st.set_page_config(
    page_title="36TB Intelligence Launcher",
    page_icon="🚀",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom CSS for launcher
st.markdown("""
<style>
/* Futuristic background */
.main > div {
    background: linear-gradient(135deg, #0c0c0c 0%, #1a1a2e 50%, #16213e 100%);
    min-height: 100vh;
    color: white;
}

/* Hide sidebar */
.css-1d391kg {
    display: none;
}

/* Center content */
.launcher-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 80vh;
    text-align: center;
}

/* Animated title */
.launcher-title {
    font-size: 4rem;
    font-weight: bold;
    background: linear-gradient(45deg, #667eea, #764ba2, #f093fb, #f5576c);
    background-size: 400% 400%;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: gradientShift 3s ease-in-out infinite;
    margin-bottom: 1rem;
}

@keyframes gradientShift {
    0%, 100% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
}

/* Subtitle */
.launcher-subtitle {
    font-size: 1.5rem;
    color: #b8b8b8;
    margin-bottom: 3rem;
}

/* Interface cards */
.interface-card {
    background: rgba(255,255,255,0.05);
    border: 2px solid rgba(255,255,255,0.1);
    border-radius: 20px;
    padding: 2rem;
    margin: 1rem;
    transition: all 0.3s ease;
    cursor: pointer;
    backdrop-filter: blur(10px);
    width: 300px;
    height: 200px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}

.interface-card:hover {
    transform: translateY(-10px);
    border-color: #667eea;
    box-shadow: 0 20px 40px rgba(102, 126, 234, 0.3);
    background: rgba(102, 126, 234, 0.1);
}

.card-icon {
    font-size: 3rem;
    margin-bottom: 1rem;
}

.card-title {
    font-size: 1.5rem;
    font-weight: bold;
    margin-bottom: 0.5rem;
}

.card-description {
    font-size: 0.9rem;
    color: #b8b8b8;
    text-align: center;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    border-radius: 15px;
    padding: 1rem 2rem;
    font-size: 1.1rem;
    font-weight: bold;
    transition: all 0.3s ease;
    width: 100%;
}

.stButton > button:hover {
    transform: translateY(-3px);
    box-shadow: 0 10px 25px rgba(102, 126, 234, 0.4);
}

/* System status */
.status-panel {
    background: rgba(0,0,0,0.3);
    border-radius: 10px;
    padding: 1rem;
    margin-top: 2rem;
    border: 1px solid rgba(255,255,255,0.1);
}

/* Animations */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

.pulse {
    animation: pulse 2s infinite;
}

@keyframes slideUp {
    from { opacity: 0; transform: translateY(30px); }
    to { opacity: 1; transform: translateY(0); }
}

.slide-up {
    animation: slideUp 0.6s ease-out;
}
</style>
""", unsafe_allow_html=True)

def main():
    """Main launcher interface."""
    
    # Add startup activity tracking
    startup_id = start_activity(ActivityType.STARTUP, "Loading 36TB Intelligence Launcher")
    
    # Render floating activity indicator
    render_floating_activity_indicator()
    
    # Animated header
    st.markdown("""
    <div class="launcher-container slide-up">
        <div class="launcher-title">🔍 36TB Intelligence</div>
        <div class="launcher-subtitle">Choose Your Experience</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Interface selection
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        <div class="interface-card">
            <div class="card-icon">⚡</div>
            <div class="card-title">Classic Interface</div>
            <div class="card-description">
                Familiar, functional interface with all core features.
                Perfect for users who prefer traditional layouts.
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("🚀 Launch Classic", key="classic", use_container_width=True):
            # Track button click
            click_id = start_activity(ActivityType.UI_INTERACTION, "Launching Classic Interface")
            launch_interface("classic")
            finish_activity(click_id, success=True)
    
    with col2:
        st.markdown("""
        <div class="interface-card">
            <div class="card-icon">🌟</div>
            <div class="card-title">Modern Interface</div>
            <div class="card-description">
                Revolutionary UX with AI-powered insights, advanced visualizations, and intelligent workflow.
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("✨ Launch Modern", key="modern", use_container_width=True):
            # Track button click
            click_id = start_activity(ActivityType.UI_INTERACTION, "Launching Modern Interface")
            launch_interface("modern")
            finish_activity(click_id, success=True)
    
    # System status with activity tracking
    status_id = start_activity(ActivityType.SYSTEM, "Checking system status")
    render_system_status()
    finish_activity(status_id, success=True)
    
    # Quick stats with activity tracking  
    stats_id = start_activity(ActivityType.SYSTEM, "Loading system statistics")
    render_quick_stats()
    finish_activity(stats_id, success=True)
    
    # Add sidebar with real-time activity monitor
    with st.sidebar:
        st.markdown("# 🔄 System Monitor")
        render_sidebar_activity_monitor()
        
        st.markdown("---")
        st.markdown("### 📊 Quick Stats")
        st.metric("Active Tasks", len(rt_monitor.get_active_activities()))
        st.metric("Total Activities", len(rt_monitor.activities))
    
    # Complete startup
    finish_activity(startup_id, success=True, message="Launcher ready")
    
    # Feature comparison
    with st.expander("🔍 Compare Interfaces"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### ⚡ Classic Interface")
            st.markdown("""
            ✅ **All core features**  
            ✅ **Fast and lightweight**  
            ✅ **Familiar navigation**  
            ✅ **Stable and tested**  
            ✅ **Low system resources**  
            
            **Perfect for:**
            - Daily file management
            - Simple searches
            - Basic analytics
            - Users who prefer simplicity
            """)
        
        with col2:
            st.markdown("### 🌟 Modern Interface")
            st.markdown("""
            ✨ **Interactive onboarding**  
            ✨ **Global search bar**  
            ✨ **Smart recommendations**  
            ✨ **Dark/Light themes**  
            ✨ **Cards-based file view**  
            ✨ **Floating action buttons**  
            ✨ **Workspace management**  
            ✨ **Advanced visualizations**  
            
            **Perfect for:**
            - Power users
            - Visual learners
            - Complex workflows
            - AI-powered insights
            """)
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666; margin-top: 2rem;">
        <p>🤖 Powered by AI • 🔍 36TB+ File Support • ☁️ Cloud Integration</p>
        <p style="font-size: 0.8rem;">Choose your interface anytime - you can switch later from settings</p>
    </div>
    """, unsafe_allow_html=True)

def launch_interface(interface_type: str):
    """Launch the selected interface."""
    
    # Track interface launch
    launch_id = start_activity(ActivityType.STARTUP, f"Starting {interface_type.title()} Interface")
    
    # Show loading animation
    with st.spinner(f"🚀 Launching {interface_type.title()} Interface..."):
        time.sleep(1)  # Brief pause for effect
    
    # Success message
    st.success(f"✅ {interface_type.title()} Interface starting!")
    
    # Save preference
    save_interface_preference(interface_type)
    
    # Launch instructions
    if interface_type == "classic":
        st.info("""
        🚀 **Classic Interface Starting...**
        
        The classic interface will open in a new browser tab.
        If it doesn't open automatically, run:
        ```
        streamlit run src/ui/app.py
        ```
        """)
        
        # Try to launch classic interface
        try:
            # Use subprocess to run the classic app
            subprocess.Popen([
                sys.executable, "-m", "streamlit", "run", 
                "src/ui/app.py", "--server.port=8501"
            ])
            
            st.markdown("""
            <div style="text-align: center; margin-top: 2rem;">
                <a href="http://localhost:8501" target="_blank" 
                   style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; padding: 1rem 2rem; border-radius: 10px; 
                          text-decoration: none; font-weight: bold;">
                    🔗 Open Classic Interface
                </a>
            </div>
            """, unsafe_allow_html=True)
            
            finish_activity(launch_id, success=True, message="Classic interface launched successfully")
            
        except Exception as e:
            st.error(f"Failed to launch classic interface: {e}")
            finish_activity(launch_id, success=False, message=f"Launch failed: {e}")
    
    else:  # modern
        st.info("""
        ✨ **Modern Interface Starting...**
        
        The modern interface will open in a new browser tab.
        If it doesn't open automatically, run:
        ```
        streamlit run src/ui/modern_app.py
        ```
        """)
        
        # Try to launch modern interface
        try:
            subprocess.Popen([
                sys.executable, "-m", "streamlit", "run", 
                "src/ui/modern_app.py", "--server.port=8503"
            ])
            
            st.markdown("""
            <div style="text-align: center; margin-top: 2rem;">
                <a href="http://localhost:8503" target="_blank" 
                   style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); 
                          color: white; padding: 1rem 2rem; border-radius: 10px; 
                          text-decoration: none; font-weight: bold;">
                    🔗 Open Modern Interface
                </a>
            </div>
            """, unsafe_allow_html=True)
            
            finish_activity(launch_id, success=True, message="Modern interface launched successfully")
            
        except Exception as e:
            st.error(f"Failed to launch modern interface: {e}")
            finish_activity(launch_id, success=False, message=f"Launch failed: {e}")

def render_system_status():
    """Render system status indicators."""
    st.markdown("### 🔧 System Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Check database
        try:
            db_path = Path("data/indexes/files.db")
            if db_path.exists():
                st.success("✅ Database Ready")
            else:
                st.warning("⚠️ Database Not Found")
        except:
            st.error("❌ Database Error")
    
    with col2:
        # Check Ollama
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                st.success("✅ AI Ready")
            else:
                st.warning("⚠️ AI Offline")
        except:
            st.warning("⚠️ AI Not Available")
    
    with col3:
        # Check dependencies
        try:
            import plotly
            import networkx
            st.success("✅ Visualizations Ready")
        except ImportError:
            st.warning("⚠️ Missing Dependencies")

def render_quick_stats():
    """Render quick system statistics."""
    st.markdown("### 📊 Quick Stats")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        try:
            # Count files in data directory
            data_path = Path("data")
            if data_path.exists():
                file_count = sum(1 for _ in data_path.rglob("*") if _.is_file())
                st.metric("Data Files", file_count)
            else:
                st.metric("Data Files", 0)
        except:
            st.metric("Data Files", "Error")
    
    with col2:
        # System info
        disk_usage = "~36TB" if Path("C:/").exists() else "Unknown"
        st.metric("System Capacity", disk_usage)
    
    with col3:
        # Check if first time user
        onboarding_file = Path("data/onboarding.json")
        user_type = "Returning" if onboarding_file.exists() else "New"
        st.metric("User Type", user_type)
    
    with col4:
        # Interface preference
        pref = load_interface_preference()
        st.metric("Last Used", pref.title() if pref else "None")

def save_interface_preference(interface: str):
    """Save user's interface preference."""
    try:
        pref_file = Path("data/interface_preference.txt")
        pref_file.parent.mkdir(exist_ok=True)
        pref_file.write_text(interface)
    except:
        pass  # Non-critical

def load_interface_preference() -> str:
    """Load user's interface preference."""
    try:
        pref_file = Path("data/interface_preference.txt")
        if pref_file.exists():
            return pref_file.read_text().strip()
    except:
        pass
    return "none"

if __name__ == "__main__":
    # Fix ScriptRunContext warnings by ensuring proper Streamlit context
    try:
        main()
    except Exception as e:
        import sys
        print(f"Error launching app: {e}")
        sys.exit(1)