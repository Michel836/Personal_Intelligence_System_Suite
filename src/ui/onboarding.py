"""Interactive onboarding system for 36TB Intelligence."""

import streamlit as st
from pathlib import Path
import json
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.core.scan_service import ScanService

class OnboardingFlow:
    """Interactive onboarding experience for new users."""
    
    def __init__(self):
        self.onboarding_file = Path("data/onboarding.json")
        self.onboarding_file.parent.mkdir(exist_ok=True)
        
    def is_first_time_user(self) -> bool:
        """Check if this is a first-time user."""
        return 'onboarding_completed' not in st.session_state or not st.session_state.onboarding_completed
    
    def start_onboarding(self):
        """Start the interactive onboarding flow."""
        if 'onboarding_step' not in st.session_state:
            st.session_state.onboarding_step = 0
            
        steps = [
            self._welcome_step,
            self._system_overview_step,
            self._first_scan_step,
            self._search_demo_step,
            self._ai_features_step,
            self._completion_step
        ]
        
        current_step = st.session_state.onboarding_step
        
        # Progress indicator
        self._render_progress_indicator(current_step, len(steps))
        
        # Current step
        if current_step < len(steps):
            steps[current_step]()
        else:
            self._complete_onboarding()
    
    def _render_progress_indicator(self, current: int, total: int):
        """Render progress indicator."""
        progress = (current + 1) / total
        st.progress(progress)
        
        st.markdown(f"""
        <div style="text-align: center; margin: 16px 0;">
            <span style="font-size: 14px; color: #666;">
                Step {current + 1} of {total} • {progress:.0%} Complete
            </span>
        </div>
        """, unsafe_allow_html=True)
    
    def _welcome_step(self):
        """Welcome step."""
        st.markdown("""
        <div style="text-align: center; padding: 40px;">
            <h1>🎉 Welcome to 36TB Intelligence!</h1>
            <h3>Your Personal Knowledge Operating System</h3>
            <p style="font-size: 18px; color: #666; margin: 24px 0;">
                Let's get you started with a quick 2-minute setup tour.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("""
            ### 🚀 What you'll learn:
            
            ✅ **How to scan and index your files**  
            ✅ **Advanced search techniques**  
            ✅ **AI-powered document analysis**  
            ✅ **Cloud sync and collaboration**  
            ✅ **Revolutionary visualizations**  
            """)
        
        if st.button("🚀 Let's Get Started!", key="start_onboarding", use_container_width=True):
            st.session_state.onboarding_step = 1
            st.rerun()
    
    def _system_overview_step(self):
        """System overview step."""
        st.markdown("""
        <div style="text-align: center;">
            <h2>📋 System Overview</h2>
            <p>36TB Intelligence is designed to help you manage, search, and understand your entire digital life.</p>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            <div style="
                padding: 24px;
                border-radius: 12px;
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                text-align: center;
                margin: 16px 0;
            ">
                <h3>🔍 Smart Search</h3>
                <p>Find any file instantly with AI-powered search across content, metadata, and relationships.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("""
            <div style="
                padding: 24px;
                border-radius: 12px;
                background: linear-gradient(135deg, #f093fb, #f5576c);
                color: white;
                text-align: center;
                margin: 16px 0;
            ">
                <h3>🤖 AI Analysis</h3>
                <p>Understand your documents with AI summaries, Q&A, and intelligent insights.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown("""
            <div style="
                padding: 24px;
                border-radius: 12px;
                background: linear-gradient(135deg, #4facfe, #00f2fe);
                color: white;
                text-align: center;
                margin: 16px 0;
            ">
                <h3>🌌 Visualizations</h3>
                <p>Explore your data with revolutionary 3D visualizations and network graphs.</p>
            </div>
            """, unsafe_allow_html=True)
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⬅️ Back", key="back_1"):
                st.session_state.onboarding_step = 0
                st.rerun()
        with col2:
            if st.button("➡️ Continue", key="continue_1"):
                st.session_state.onboarding_step = 2
                st.rerun()
    
    def _first_scan_step(self):
        """First scan step."""
        st.markdown("""
        <div style="text-align: center;">
            <h2>🚀 Your First Scan</h2>
            <p>Let's scan your system to build your personal file index.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Scan options
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            ### 📁 What to Scan?
            
            **Recommended for beginners:**
            - Documents folder
            - Desktop files
            - Downloads folder
            
            **Advanced users:**
            - Entire system scan
            - Custom directory selection
            """)
        
        with col2:
            st.markdown("""
            ### ⚡ Quick Start Options
            
            Choose your scanning preference:
            """)
            
            scan_option = st.radio(
                "Scanning Options",
                ["🏠 Scan common folders (Recommended)", "🌍 Full system scan", "📂 Choose specific folders"],
                key="scan_option",
                label_visibility="collapsed"
            )
        
        if st.button("🚀 Start Scanning", key="start_scan", use_container_width=True):
            self._perform_demo_scan(scan_option)
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⬅️ Back", key="back_2"):
                st.session_state.onboarding_step = 1
                st.rerun()
        with col2:
            if st.button("⏭️ Skip Scan", key="skip_scan"):
                st.session_state.onboarding_step = 3
                st.rerun()
    
    def _search_demo_step(self):
        """Search demonstration step."""
        st.markdown("""
        <div style="text-align: center;">
            <h2>🔍 Search Like a Pro</h2>
            <p>Now let's explore the powerful search capabilities.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Interactive search demo
        st.markdown("### 🎯 Try These Search Examples:")
        
        examples = [
            {"query": "type:pdf", "description": "Find all PDF files"},
            {"query": "size:>10MB", "description": "Find large files over 10MB"},
            {"query": "modified:today", "description": "Files modified today"},
            {"query": "python code", "description": "Semantic search for Python code"}
        ]
        
        for example in examples:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.code(example["query"], language="text")
                st.caption(example["description"])
            with col2:
                if st.button(f"Try It", key=f"try_{example['query']}"):
                    st.session_state.demo_search = example["query"]
                    st.info(f"Great! You searched for: `{example['query']}`")
        
        # Search tips
        with st.expander("💡 Pro Search Tips"):
            st.markdown("""
            - **File Types**: `type:document`, `type:image`, `type:video`
            - **Size Filters**: `size:<1MB`, `size:>100MB`
            - **Date Ranges**: `modified:last_week`, `created:2024`
            - **Extensions**: `extension:py`, `extension:jpg`
            - **Content Search**: Just type naturally - AI will understand!
            """)
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⬅️ Back", key="back_3"):
                st.session_state.onboarding_step = 2
                st.rerun()
        with col2:
            if st.button("➡️ Continue", key="continue_3"):
                st.session_state.onboarding_step = 4
                st.rerun()
    
    def _ai_features_step(self):
        """AI features demonstration step."""
        st.markdown("""
        <div style="text-align: center;">
            <h2>🤖 AI-Powered Intelligence</h2>
            <p>Discover how AI transforms your document experience.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # AI feature showcase
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            ### 💬 AI Chat
            
            Ask questions about your documents:
            - "Summarize my research papers"
            - "Find emails about project X"
            - "What documents mention artificial intelligence?"
            """)
            
            if st.button("🧠 Try AI Chat", key="try_ai_chat"):
                st.success("AI Chat activated! You can now ask questions about your files.")
        
        with col2:
            st.markdown("""
            ### 📊 Smart Analysis
            
            Get intelligent insights:
            - Document summaries
            - Key topic extraction
            - Content relationships
            - Duplicate detection
            """)
            
            if st.button("📈 View Analytics", key="try_analytics"):
                st.success("Analytics ready! Check the Dashboard for insights.")
        
        # AI model status
        st.markdown("### 🔧 AI Model Status")
        try:
            chat_engine = st.session_state.chat_engine
            model_status = chat_engine.get_model_status()
            if model_status.get('available', False):
                st.success(f"✅ AI Model Ready: {model_status.get('current_model', 'Unknown')}")
            else:
                st.warning("⚠️ AI Model Not Available - Install Ollama for full AI features")
        except:
            st.error("❌ AI System Error - Check configuration")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⬅️ Back", key="back_4"):
                st.session_state.onboarding_step = 3
                st.rerun()
        with col2:
            if st.button("➡️ Continue", key="continue_4"):
                st.session_state.onboarding_step = 5
                st.rerun()
    
    def _completion_step(self):
        """Onboarding completion step."""
        st.markdown("""
        <div style="text-align: center; padding: 40px;">
            <h1>🎉 You're All Set!</h1>
            <h3>Welcome to your new digital command center</h3>
            <p style="font-size: 18px; color: #666; margin: 24px 0;">
                You now have access to the most advanced personal file intelligence system.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Quick access cards
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔍 Start Searching", key="goto_search", use_container_width=True):
                st.session_state.onboarding_completed = True
                st.session_state.current_page = "Search"
                st.rerun()
        
        with col2:
            if st.button("🏠 Go to Dashboard", key="goto_dashboard", use_container_width=True):
                st.session_state.onboarding_completed = True
                st.session_state.current_page = "Dashboard"
                st.rerun()
        
        with col3:
            if st.button("🌌 Explore Visualizations", key="goto_viz", use_container_width=True):
                st.session_state.onboarding_completed = True
                st.session_state.current_page = "Visualizations"
                st.rerun()
        
        # Tips for getting started
        st.markdown("### 💡 Next Steps:")
        st.info("""
        1. **🚀 Run a full system scan** to index all your files
        2. **🔄 Extract content** from documents for better search
        3. **☁️ Set up cloud sync** to backup your index
        4. **🏷️ Start tagging** important files for quick access
        5. **🤖 Explore AI features** to unlock document intelligence
        """)
        
        if st.button("🎯 Complete Setup", key="complete_onboarding", use_container_width=True):
            self._complete_onboarding()
    
    def _perform_demo_scan(self, scan_option: str):
        """Perform demonstration scan."""
        with st.spinner("Scanning your files..."):
            try:
                scanner = st.session_state.scanner
                
                scan_root = None
                if "common folders" in scan_option.lower():
                    # Scan common directories
                    scan_root = Path("C:\\Users")
                    files = list(scanner.fast_scan(scan_root, limit=500))
                elif "full system" in scan_option.lower():
                    # Full system scan
                    scan_root = Path("C:\\")
                    files = list(scanner.fast_scan(scan_root, limit=1000))
                else:
                    # Custom scan (mock for demo)
                    files = []

                if scan_root is not None:
                    session = ScanService(st.session_state.db).session(scan_root)
                    try:
                        if files:
                            session.record(files)
                        session.complete()
                    except Exception as scan_error:
                        session.fail(str(scan_error))

                if files:
                    st.success(f"✅ Scanned {len(files)} files!")
                else:
                    st.success("✅ Demo scan completed!")
                
                st.session_state.onboarding_step = 3
                st.rerun()
                
            except Exception as e:
                st.error(f"Scan error: {e}")
                st.info("Don't worry - you can run scans later from the Dashboard!")
    
    def _complete_onboarding(self):
        """Complete the onboarding process."""
        st.session_state.onboarding_completed = True
        st.session_state.onboarding_step = 0
        
        # Save onboarding completion
        completion_data = {
            "completed_at": datetime.now().isoformat(),
            "version": "1.0",
            "user_preferences": st.session_state.get("user_preferences", {})
        }
        
        try:
            with open(self.onboarding_file, 'w') as f:
                json.dump(completion_data, f, indent=2)
        except:
            pass  # Non-critical
        
        st.success("🎉 Onboarding completed! Welcome to 36TB Intelligence!")
        st.rerun()

class NavigationManager:
    """Advanced navigation system with breadcrumbs and context."""
    
    def __init__(self):
        self.navigation_history = []
        self.breadcrumbs = []
    
    def render_navigation(self):
        """Render advanced navigation system."""
        # Breadcrumb navigation
        if 'current_page' in st.session_state:
            self._render_breadcrumbs()
        
        # Navigation shortcuts
        self._render_navigation_shortcuts()
    
    def _render_breadcrumbs(self):
        """Render breadcrumb navigation."""
        current_page = st.session_state.get('current_page', 'Dashboard')
        
        breadcrumb_items = ['Home', current_page]
        
        # Add context-specific breadcrumbs
        if hasattr(st.session_state, 'search_query') and st.session_state.search_query:
            breadcrumb_items.append(f'Search: "{st.session_state.search_query}"')
        
        # Render breadcrumbs
        st.markdown("""
        <style>
        .breadcrumb-nav {
            background: #f8f9fa;
            padding: 8px 16px;
            border-radius: 4px;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .breadcrumb-item {
            color: #007bff;
            text-decoration: none;
            margin-right: 8px;
        }
        .breadcrumb-separator {
            color: #6c757d;
            margin-right: 8px;
        }
        </style>
        """, unsafe_allow_html=True)
        
        breadcrumb_html = '<div class="breadcrumb-nav">'
        for i, item in enumerate(breadcrumb_items):
            if i > 0:
                breadcrumb_html += '<span class="breadcrumb-separator">›</span>'
            breadcrumb_html += f'<span class="breadcrumb-item">{item}</span>'
        breadcrumb_html += '</div>'
        
        st.markdown(breadcrumb_html, unsafe_allow_html=True)
    
    def _render_navigation_shortcuts(self):
        """Render keyboard navigation shortcuts."""
        st.markdown("""
        <div style="
            position: fixed;
            bottom: 10px;
            left: 10px;
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 8px;
            border-radius: 4px;
            font-size: 11px;
            z-index: 999;
        ">
            <div>🔍 Ctrl+K: Search</div>
            <div>🏠 Ctrl+H: Home</div>
            <div>⚙️ Ctrl+,: Settings</div>
        </div>
        """, unsafe_allow_html=True)