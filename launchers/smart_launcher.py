"""Smart Launcher with Module Selection - Optimize Startup Performance"""

import streamlit as st
import json
from pathlib import Path
from typing import Dict, List, Set
import subprocess
import sys
import os
import psutil
import time

# Configuration file for module preferences
CONFIG_FILE = Path("data/launcher_config.json")

# Available modules with their dependencies and resource usage
MODULES = {
    "core": {
        "name": "Core System",
        "description": "Database, basic file operations",
        "required": True,
        "memory_mb": 30,
        "startup_time": 1,
        "imports": ["database", "models", "config"]
    },
    "ai_chat": {
        "name": "AI Chat Engine",
        "description": "Ollama integration for chat with documents",
        "required": False,
        "memory_mb": 500,
        "startup_time": 5,
        "imports": ["chat_engine", "ollama"],
        "requires": ["embeddings"]
    },
    "embeddings": {
        "name": "Semantic Search",
        "description": "AI embeddings for semantic search",
        "required": False,
        "memory_mb": 1500,
        "startup_time": 8,
        "imports": ["semantic_search", "embeddings"]
    },
    "scanner": {
        "name": "File Scanner",
        "description": "Fast file indexing engine",
        "required": False,
        "memory_mb": 100,
        "startup_time": 2,
        "imports": ["scanner", "fast_engine"]
    },
    "extractors": {
        "name": "Content Extractors",
        "description": "PDF, Office, text extraction",
        "required": False,
        "memory_mb": 200,
        "startup_time": 3,
        "imports": ["pdf_extractor", "office_extractor", "text_extractor"]
    },
    "visualizations": {
        "name": "Advanced Visualizations",
        "description": "Plotly, NetworkX graphs",
        "required": False,
        "memory_mb": 150,
        "startup_time": 2,
        "imports": ["plotly", "networkx", "advanced_viz"]
    },
    "cloud_sync": {
        "name": "Cloud Sync",
        "description": "Google Drive, OneDrive integration",
        "required": False,
        "memory_mb": 50,
        "startup_time": 1,
        "imports": ["cloud_sync", "sync_manager"]
    },
    "monitoring": {
        "name": "Real-time Monitoring",
        "description": "Activity tracking and system monitoring",
        "required": False,
        "memory_mb": 20,
        "startup_time": 0.5,
        "imports": ["real_time_monitor"]
    },
    "advanced_search": {
        "name": "Advanced Search",
        "description": "Regex, filters, complex queries",
        "required": False,
        "memory_mb": 50,
        "startup_time": 1,
        "imports": ["advanced_search", "search_filters"]
    },
    "analytics": {
        "name": "Analytics Dashboard",
        "description": "Statistics and insights",
        "required": False,
        "memory_mb": 80,
        "startup_time": 1.5,
        "imports": ["analytics", "dashboard"]
    }
}

# Preset configurations
PRESETS = {
    "minimal": {
        "name": "🚀 Minimal (Fastest)",
        "description": "Core + Scanner only",
        "modules": ["core", "scanner"],
        "memory": "~130 MB",
        "startup": "~3 seconds"
    },
    "standard": {
        "name": "⭐ Standard",
        "description": "Core + Scanner + Search + Monitoring",
        "modules": ["core", "scanner", "advanced_search", "monitoring"],
        "memory": "~200 MB",
        "startup": "~5 seconds"
    },
    "ai_powered": {
        "name": "🤖 AI-Powered",
        "description": "Standard + AI Chat + Semantic Search",
        "modules": ["core", "scanner", "advanced_search", "monitoring", "ai_chat", "embeddings"],
        "memory": "~2.3 GB",
        "startup": "~15 seconds"
    },
    "full": {
        "name": "💪 Full Power",
        "description": "All modules enabled",
        "modules": list(MODULES.keys()),
        "memory": "~2.8 GB",
        "startup": "~25 seconds"
    },
    "custom": {
        "name": "🔧 Custom",
        "description": "Choose your modules",
        "modules": [],
        "memory": "Variable",
        "startup": "Variable"
    }
}

def load_config() -> Dict:
    """Load saved configuration."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "last_preset": "standard",
        "custom_modules": ["core", "scanner"],
        "auto_start": False
    }

def save_config(config: Dict):
    """Save configuration."""
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def calculate_resources(modules: List[str]) -> Dict:
    """Calculate total resources for selected modules."""
    total_memory = 0
    total_time = 0
    
    for module in modules:
        if module in MODULES:
            total_memory += MODULES[module]["memory_mb"]
            total_time += MODULES[module]["startup_time"]
    
    return {
        "memory_mb": total_memory,
        "startup_time": total_time,
        "module_count": len(modules)
    }

def check_dependencies(modules: Set[str]) -> Set[str]:
    """Check and add required dependencies."""
    final_modules = modules.copy()
    
    for module in modules:
        if module in MODULES:
            # Add required dependencies
            if "requires" in MODULES[module]:
                for req in MODULES[module]["requires"]:
                    final_modules.add(req)
    
    # Always include core
    final_modules.add("core")
    
    return final_modules

def generate_launch_script(modules: List[str], interface: str = "classic") -> str:
    """Generate optimized launch script based on selected modules."""
    
    script = f'''"""Auto-generated launcher with selected modules only"""
import os
os.environ["MODULES_ENABLED"] = "{','.join(modules)}"

# Lazy imports based on selected modules
import streamlit as st
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

# Core imports (always needed)
from src.core.database import DatabaseManager
from src.core.models import FileInfo
from src.core.config import Settings

# Initialize session state with selected modules
if 'enabled_modules' not in st.session_state:
    st.session_state.enabled_modules = {modules}
    st.session_state.db = DatabaseManager()
'''
    
    # Add conditional imports based on modules
    if "scanner" in modules:
        script += '''
# Scanner module
from src.scanner.fast_engine import FastScannerEngine
if 'scanner' not in st.session_state:
    st.session_state.scanner = FastScannerEngine()
'''
    
    if "ai_chat" in modules:
        script += '''
# AI Chat module
from src.intelligence.chat_engine import ChatEngine
if 'chat_engine' not in st.session_state:
    st.session_state.chat_engine = ChatEngine()
'''
    
    if "embeddings" in modules:
        script += '''
# Semantic Search module
from src.intelligence.semantic_search import SemanticSearchEngine
if 'semantic_search' not in st.session_state:
    st.session_state.semantic_search = SemanticSearchEngine()
'''
    
    if "monitoring" in modules:
        script += '''
# Real-time Monitoring
from src.ui.real_time_monitor import rt_monitor, render_floating_activity_indicator
render_floating_activity_indicator()
'''
    
    # Add main app import
    if interface == "modern":
        script += '''
# Launch modern interface
from src.ui.modern_app import main
'''
    else:
        script += '''
# Launch classic interface
from src.ui.app import main
'''
    
    script += '''
if __name__ == "__main__":
    main()
'''
    
    return script

def main():
    """Smart launcher interface."""
    
    st.set_page_config(
        page_title="36TB Intelligence - Smart Launcher",
        page_icon="🎯",
        layout="wide"
    )
    
    # Load configuration
    config = load_config()
    
    # Header
    st.title("🎯 36TB Intelligence - Smart Launcher")
    st.markdown("Optimize startup performance by selecting only the modules you need")
    
    # System info
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_ram = psutil.virtual_memory().total / (1024**3)
        st.metric("System RAM", f"{total_ram:.1f} GB")
    with col2:
        available_ram = psutil.virtual_memory().available / (1024**3)
        st.metric("Available RAM", f"{available_ram:.1f} GB")
    with col3:
        cpu_count = psutil.cpu_count()
        st.metric("CPU Cores", cpu_count)
    with col4:
        current_usage = psutil.Process().memory_info().rss / (1024**2)
        st.metric("Current Usage", f"{current_usage:.0f} MB")
    
    st.markdown("---")
    
    # Preset selection
    st.subheader("🎨 Choose Configuration Preset")
    
    preset_cols = st.columns(len(PRESETS))
    selected_preset = None
    
    for i, (preset_id, preset_info) in enumerate(PRESETS.items()):
        with preset_cols[i]:
            st.markdown(f"### {preset_info['name']}")
            st.caption(preset_info['description'])
            st.info(f"💾 {preset_info['memory']}")
            st.info(f"⏱️ {preset_info['startup']}")
            
            if st.button(f"Select", key=f"preset_{preset_id}", use_container_width=True):
                selected_preset = preset_id
                st.session_state.selected_preset = preset_id
    
    # Get selected preset from session or default
    if selected_preset is None:
        selected_preset = st.session_state.get('selected_preset', config['last_preset'])
    
    st.markdown("---")
    
    # Module selection for custom preset
    if selected_preset == "custom":
        st.subheader("🔧 Custom Module Selection")
        
        selected_modules = set()
        
        # Create checkboxes for each module
        cols = st.columns(3)
        for i, (module_id, module_info) in enumerate(MODULES.items()):
            col_idx = i % 3
            with cols[col_idx]:
                if module_info["required"]:
                    st.checkbox(
                        f"✅ {module_info['name']} (Required)",
                        value=True,
                        disabled=True,
                        key=f"module_{module_id}"
                    )
                    selected_modules.add(module_id)
                else:
                    if st.checkbox(
                        f"{module_info['name']}",
                        help=f"{module_info['description']} | 💾 {module_info['memory_mb']}MB | ⏱️ {module_info['startup_time']}s",
                        key=f"module_{module_id}",
                        value=module_id in config.get('custom_modules', [])
                    ):
                        selected_modules.add(module_id)
        
        # Check dependencies
        selected_modules = check_dependencies(selected_modules)
        
    else:
        selected_modules = set(PRESETS[selected_preset]["modules"])
    
    # Calculate resources
    resources = calculate_resources(list(selected_modules))
    
    # Display resource summary
    st.markdown("---")
    st.subheader("📊 Resource Estimation")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Modules Selected", resources["module_count"])
    with col2:
        st.metric("Estimated RAM", f"{resources['memory_mb']} MB")
    with col3:
        st.metric("Startup Time", f"~{resources['startup_time']:.1f} seconds")
    
    # Progress bar for RAM usage
    ram_percentage = (resources['memory_mb'] / 1024) / total_ram * 100
    st.progress(min(ram_percentage / 100, 1.0), text=f"RAM Usage: {ram_percentage:.1f}% of system")
    
    # Interface selection
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        interface = st.radio(
            "🖥️ Select Interface",
            ["classic", "modern"],
            format_func=lambda x: "⚡ Classic Interface" if x == "classic" else "🌟 Modern Interface"
        )
    
    with col2:
        st.markdown("### ⚙️ Options")
        auto_start = st.checkbox("Auto-start with this config next time", value=config.get('auto_start', False))
        save_config_btn = st.checkbox("Save configuration", value=True)
    
    # Launch button
    st.markdown("---")
    
    if st.button("🚀 Launch 36TB Intelligence", type="primary", use_container_width=True):
        # Save configuration if requested
        if save_config_btn:
            new_config = {
                "last_preset": selected_preset,
                "custom_modules": list(selected_modules),
                "auto_start": auto_start,
                "interface": interface
            }
            save_config(new_config)
            st.success("✅ Configuration saved!")
        
        # Generate and save launch script
        launch_script = generate_launch_script(list(selected_modules), interface)
        temp_launcher = Path("temp_optimized_launcher.py")
        with open(temp_launcher, 'w', encoding='utf-8') as f:
            f.write(launch_script)
        
        # Show launching message
        with st.spinner(f"🚀 Launching with {len(selected_modules)} modules..."):
            time.sleep(1)
            
            # Launch the optimized version
            port = 8505 if interface == "classic" else 8506
            subprocess.Popen([
                sys.executable, "-m", "streamlit", "run",
                str(temp_launcher), f"--server.port={port}"
            ])
            
            st.success(f"✅ Launched on http://localhost:{port}")
            st.balloons()
    
    # Quick comparison table
    with st.expander("📊 Module Comparison Table"):
        module_data = []
        for module_id, module_info in MODULES.items():
            module_data.append({
                "Module": module_info["name"],
                "Required": "✅" if module_info["required"] else "❌",
                "RAM (MB)": module_info["memory_mb"],
                "Startup (s)": module_info["startup_time"],
                "Description": module_info["description"]
            })
        
        st.dataframe(module_data, use_container_width=True)
    
    # Tips
    with st.expander("💡 Performance Tips"):
        st.markdown("""
        ### Optimization Recommendations:
        
        1. **For Quick File Browsing**: Use "Minimal" preset (130MB RAM)
        2. **For Daily Use**: Use "Standard" preset (200MB RAM)
        3. **For AI Features**: Use "AI-Powered" preset (2.3GB RAM)
        4. **For Development**: Use "Full Power" preset (2.8GB RAM)
        
        ### Module Guidelines:
        - **Embeddings**: Only needed for semantic search (uses 1.5GB)
        - **AI Chat**: Requires Ollama running (uses 500MB)
        - **Visualizations**: Only for advanced graphs (uses 150MB)
        - **Cloud Sync**: Only if using Google Drive/OneDrive (uses 50MB)
        
        ### Startup Time Optimization:
        - Each module adds to startup time
        - Modules load in parallel when possible
        - First launch is slower (model downloads)
        - Subsequent launches use cache
        """)

if __name__ == "__main__":
    main()