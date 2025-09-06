"""Advanced disk and path selection component."""

import streamlit as st
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import os

from src.utils.disk_utils import get_available_drives, get_recommended_drives, validate_scan_path

class DiskSelector:
    """Advanced disk and path selection interface."""
    
    def __init__(self):
        self.selected_paths = []
        
    def render_disk_selection(self, key_prefix: str = "disk_sel") -> List[str]:
        """Render disk selection interface."""
        st.markdown("### 💽 Select Drives & Paths to Scan")
        
        # Get available drives
        drives = get_available_drives()
        recommended = get_recommended_drives()
        
        if not drives:
            st.error("No drives detected!")
            return []
        
        # Overview section
        self._render_drives_overview(drives, key_prefix)
        
        # Selection method
        selection_method = st.radio(
            "Selection Method:",
            ["🎯 Quick Select (Recommended)", "🔧 Manual Selection", "📂 Custom Paths"],
            key=f"{key_prefix}_method"
        )
        
        selected_paths = []
        
        if selection_method == "🎯 Quick Select (Recommended)":
            selected_paths = self._render_quick_select(drives, recommended, key_prefix)
            
        elif selection_method == "🔧 Manual Selection":
            selected_paths = self._render_manual_selection(drives, key_prefix)
            
        else:  # Custom Paths
            selected_paths = self._render_custom_paths(key_prefix)
        
        # Summary
        if selected_paths:
            self._render_selection_summary(selected_paths)
        
        return selected_paths
    
    def _render_drives_overview(self, drives: List[Dict], key_prefix: str):
        """Render overview of available drives with quick actions."""
        st.markdown("#### 📊 Disques Disponibles - Vue d'Ensemble")
        
        # Calculate totals
        total_drives = len(drives)
        total_space = sum(d.get('total_space', 0) for d in drives)
        total_free = sum(d.get('free_space', 0) for d in drives)
        
        # Drive types count
        drive_types = {}
        for drive in drives:
            dtype = drive.get('type', 'unknown')
            drive_types[dtype] = drive_types.get(dtype, 0) + 1
        
        # Overview metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("💽 Nombre de disques", total_drives)
        
        with col2:
            st.metric("📦 Espace total", self._format_bytes(total_space))
        
        with col3:
            st.metric("💾 Espace libre", self._format_bytes(total_free))
        
        with col4:
            used_percent = ((total_space - total_free) / total_space * 100) if total_space > 0 else 0
            st.metric("📈 Utilisation", f"{used_percent:.1f}%")
        
        # Drive types breakdown
        st.markdown("**Types de disques détectés:**")
        type_names = {
            'fixed': '💽 Disques fixes',
            'removable': '💾 Disques amovibles', 
            'remote': '🌐 Disques réseau',
            'cdrom': '💿 Lecteurs CD/DVD',
            'ramdisk': '🧠 Disques RAM'
        }
        
        type_cols = st.columns(len(drive_types))
        for i, (dtype, count) in enumerate(drive_types.items()):
            with type_cols[i]:
                type_display = type_names.get(dtype, f'❓ {dtype.title()}')
                st.info(f"{type_display}: **{count}**")
        
        # Quick selection buttons
        st.markdown("**Actions rapides:**")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("✅ Tout sélectionner", key=f"{key_prefix}_select_all"):
                # Store selection in session state for use by selection methods
                st.session_state[f"{key_prefix}_select_all_drives"] = True
                st.rerun()
        
        with col2:
            if st.button("❌ Tout désélectionner", key=f"{key_prefix}_select_none"):
                st.session_state[f"{key_prefix}_select_none_drives"] = True
                st.rerun()
        
        with col3:
            if st.button("🔥 Disques fixes seulement", key=f"{key_prefix}_select_fixed"):
                st.session_state[f"{key_prefix}_select_fixed_only"] = True
                st.rerun()
        
        with col4:
            if st.button("🎯 Sélection recommandée", key=f"{key_prefix}_select_recommended_btn"):
                # Use a different key for the session state variable
                st.session_state[f"{key_prefix}_select_recommended_action"] = True
                st.rerun()
        
        st.markdown("---")
    
    def _render_quick_select(self, drives: List[Dict], recommended: List[str], key_prefix: str) -> List[str]:
        """Render quick selection interface."""
        st.markdown("**🚀 Quick selection of recommended drives:**")
        
        if not recommended:
            st.warning("No recommended drives found. Use manual selection.")
            return []
        
        # Show recommended drives with details
        selected = []
        
        for drive_path in recommended:
            drive_info = next((d for d in drives if d['path'] == drive_path), None)
            if not drive_info:
                continue
            
            col1, col2 = st.columns([1, 3])
            
            with col1:
                include = st.checkbox(
                    "Include",
                    value=True,
                    key=f"{key_prefix}_quick_{drive_info['path']}"
                )
            
            with col2:
                # Drive info card
                self._render_drive_card(drive_info, compact=True)
            
            if include:
                selected.append(drive_info['path'])
        
        return selected
    
    def _render_manual_selection(self, drives: List[Dict], key_prefix: str) -> List[str]:
        """Render manual drive selection."""
        st.markdown("**🔧 Sélection manuelle des disques:**")
        
        # Check for quick action states
        select_all = st.session_state.get(f"{key_prefix}_select_all_drives", False)
        select_none = st.session_state.get(f"{key_prefix}_select_none_drives", False)
        select_fixed = st.session_state.get(f"{key_prefix}_select_fixed_only", False)
        select_recommended = st.session_state.get(f"{key_prefix}_select_recommended_action", False)
        
        # Clear states after reading
        if select_all:
            st.session_state[f"{key_prefix}_select_all_drives"] = False
        if select_none:
            st.session_state[f"{key_prefix}_select_none_drives"] = False
        if select_fixed:
            st.session_state[f"{key_prefix}_select_fixed_only"] = False
        if select_recommended:
            st.session_state[f"{key_prefix}_select_recommended_action"] = False
        
        selected = []
        
        # Group drives by type
        drive_groups = {}
        type_names = {
            'fixed': '💽 Disques fixes',
            'removable': '💾 Disques amovibles', 
            'remote': '🌐 Disques réseau',
            'cdrom': '💿 Lecteurs CD/DVD',
            'ramdisk': '🧠 Disques RAM'
        }
        
        for drive in drives:
            drive_type = drive.get('type', 'unknown')
            if drive_type not in drive_groups:
                drive_groups[drive_type] = []
            drive_groups[drive_type].append(drive)
        
        # Render each group
        for drive_type, group_drives in drive_groups.items():
            if not group_drives:
                continue
            
            type_display = type_names.get(drive_type, f'❓ {drive_type.title()}')
            with st.expander(f"{type_display} ({len(group_drives)})", expanded=True):
                
                for drive in group_drives:
                    col1, col2 = st.columns([1, 4])
                    
                    with col1:
                        # Determine default value based on quick actions
                        default_value = False
                        if select_all:
                            default_value = True
                        elif select_fixed and drive_type == 'fixed':
                            default_value = True
                        elif select_recommended:
                            # Check if this drive is recommended
                            recommended = get_recommended_drives()
                            default_value = drive['path'] in recommended
                        
                        include = st.checkbox(
                            "Sélectionner",
                            value=default_value,
                            key=f"{key_prefix}_manual_{drive['path'].replace(':', '_')}",
                            help=f"Inclure {drive['path']} dans le scan"
                        )
                    
                    with col2:
                        self._render_drive_card(drive, compact=False)
                    
                    if include:
                        selected.append(drive['path'])
        
        return selected
    
    def _render_custom_paths(self, key_prefix: str) -> List[str]:
        """Render custom path input."""
        st.markdown("**📂 Custom paths to scan:**")
        
        # Path input methods
        input_method = st.radio(
            "Input Method:",
            ["📝 Text Input", "📁 Folder Browser"],
            key=f"{key_prefix}_input_method"
        )
        
        paths = []
        
        if input_method == "📝 Text Input":
            # Multi-line text input
            path_text = st.text_area(
                "Enter paths (one per line):",
                placeholder="C:\\Users\\YourName\\Documents\nD:\\Projects\nE:\\Data",
                key=f"{key_prefix}_custom_paths",
                height=150
            )
            
            if path_text:
                paths = [line.strip() for line in path_text.split('\n') if line.strip()]
        
        else:  # Folder Browser (limited in Streamlit)
            st.info("💡 **Tip**: Use text input method for multiple paths")
            
            # Single path input with validation
            custom_path = st.text_input(
                "Enter folder path:",
                placeholder="C:\\Users\\YourName\\Documents",
                key=f"{key_prefix}_single_path"
            )
            
            if custom_path:
                paths = [custom_path]
        
        # Validate paths
        validated_paths = []
        for path in paths:
            if path:
                validation = validate_scan_path(path)
                
                col1, col2 = st.columns([1, 3])
                with col1:
                    if validation['valid']:
                        st.success("✅ Valid")
                        validated_paths.append(path)
                    else:
                        st.error("❌ Invalid")
                
                with col2:
                    st.write(f"**{path}**")
                    if validation['warnings']:
                        for warning in validation['warnings']:
                            st.warning(f"⚠️ {warning}")
                    if validation['errors']:
                        for error in validation['errors']:
                            st.error(f"❌ {error}")
                    if validation['estimated_files']:
                        st.info(f"📊 Estimated ~{validation['estimated_files']:,} files")
        
        return validated_paths
    
    def _render_drive_card(self, drive: Dict[str, Any], compact: bool = False):
        """Render a drive information card using native Streamlit components."""
        # Calculate usage
        usage = drive.get('usage_percent', 0)
        
        # Format sizes
        total_size = self._format_bytes(drive.get('total_space', 0))
        used_size = self._format_bytes(drive.get('used_space', 0))
        free_size = self._format_bytes(drive.get('free_space', 0))
        
        # Drive type icon
        type_icons = {
            'fixed': '💽',
            'removable': '💾', 
            'remote': '🌐',
            'cdrom': '💿',
            'ramdisk': '🧠',
            'unknown': '❓'
        }
        
        icon = type_icons.get(drive.get('type', 'unknown'), '💽')
        
        if compact:
            # Compact display
            col1, col2 = st.columns([1, 4])
            with col1:
                st.markdown(f"**{icon}**")
            with col2:
                st.markdown(f"**{drive['path']}** {drive.get('label', '')}")
                st.caption(f"{total_size} total • {free_size} free • {usage:.1f}% used")
        else:
            # Full card display
            with st.container():
                # Header
                col1, col2 = st.columns([1, 6])
                with col1:
                    st.markdown(f"<div style='font-size: 32px; text-align: center;'>{icon}</div>", unsafe_allow_html=True)
                with col2:
                    st.markdown(f"### {drive['path']}")
                    st.caption(drive.get('label', 'Local Disk'))
                
                # Storage info
                st.markdown(f"**Storage:** {used_size} / {total_size}")
                
                # Progress bar
                st.progress(usage / 100, text=f"{usage:.1f}% used")
                
                # Details
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Used", f"{usage:.1f}%", delta=None)
                with col2:
                    st.metric("Free", free_size, delta=None)
                with col3:
                    st.metric("Type", drive.get('type', 'unknown').title(), delta=None)
                
                st.divider()
    
    def _render_selection_summary(self, selected_paths: List[str]):
        """Render summary of selected paths."""
        if not selected_paths:
            return
            
        st.markdown("### 📋 Résumé de la Sélection")
        
        # Get drive info for selected paths
        drives = get_available_drives()
        selected_drives = [d for d in drives if d['path'] in selected_paths]
        
        total_estimated_files = 0
        total_space = sum(d.get('total_space', 0) for d in selected_drives)
        total_free = sum(d.get('free_space', 0) for d in selected_drives)
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("🔍 Disques sélectionnés", len(selected_paths))
        
        with col2:
            st.metric("📦 Espace total", self._format_bytes(total_space))
        
        with col3:
            st.metric("💾 Espace libre", self._format_bytes(total_free))
        
        with col4:
            if total_space > 0:
                used_percent = ((total_space - total_free) / total_space * 100)
                st.metric("📊 Utilisation moy.", f"{used_percent:.1f}%")
            else:
                st.metric("📊 Utilisation", "N/A")
        
        # Detailed list
        st.markdown("**Détails des disques sélectionnés:**")
        
        for i, path in enumerate(selected_paths):
            validation = validate_scan_path(path)
            drive_info = next((d for d in selected_drives if d['path'] == path), None)
            
            with st.expander(f"📀 {i+1}. {path} - {drive_info.get('label', 'Disque local') if drive_info else 'Chemin personnalisé'}", expanded=False):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if validation['estimated_files']:
                        st.write(f"📄 **Fichiers estimés**: ~{validation['estimated_files']:,}")
                        total_estimated_files += validation['estimated_files']
                    else:
                        st.write("📄 **Fichiers**: Estimation en cours...")
                
                with col2:
                    if drive_info:
                        st.write(f"💽 **Type**: {drive_info.get('type', 'unknown').title()}")
                        st.write(f"📦 **Taille**: {self._format_bytes(drive_info.get('total_space', 0))}")
                    else:
                        st.write("💽 **Type**: Chemin personnalisé")
                
                with col3:
                    if validation['valid']:
                        st.success("✅ Prêt à scanner")
                    else:
                        st.error("❌ Problèmes détectés")
                        for error in validation.get('errors', []):
                            st.write(f"• {error}")
        
        # Final summary
        if total_estimated_files > 0:
            st.info(f"🎯 **Total estimé**: ~{total_estimated_files:,} fichiers à scanner sur {len(selected_paths)} disque(s)")
        
        # Warning for large scans
        if total_estimated_files > 100000:
            st.warning(f"⚠️ **Scan important**: Plus de {total_estimated_files:,} fichiers détectés. Le scan peut prendre du temps.")
        elif total_estimated_files > 50000:
            st.info(f"ℹ️ **Scan moyen**: {total_estimated_files:,} fichiers détectés. Durée estimée: quelques minutes.")
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes to human readable string."""
        if bytes_val == 0:
            return "0 B"
        
        sizes = ["B", "KB", "MB", "GB", "TB", "PB"]
        i = 0
        size = float(bytes_val)
        
        while size >= 1024 and i < len(sizes) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {sizes[i]}"