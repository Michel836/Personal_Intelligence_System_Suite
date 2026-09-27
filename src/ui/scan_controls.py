"""Advanced scan control interface with progress tracking."""

import streamlit as st
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

class ScanController:
    """Advanced scan control interface with real-time progress."""
    
    def __init__(self):
        self.scan_state = {
            'status': 'idle',  # idle, running, paused, completed, cancelled
            'progress': 0.0,
            'current_file': '',
            'files_processed': 0,
            'total_files': 0,
            'files_per_second': 0.0,
            'start_time': None,
            'elapsed_time': 0,
            'eta': None,
            'current_path': '',
            'errors': 0
        }
    
    def render_scan_controls(self, scanner_engine=None, key_prefix="scan_ctrl") -> str:
        """Render scan control interface with progress bars."""
        
        st.markdown("### 🎛️ Scan Controls")
        
        # Check for progress updates from background thread
        self._check_progress_updates()
        
        # Only show controls if there's been scan activity or scan is running
        if self.scan_state['status'] in ['idle'] and self.scan_state['files_processed'] == 0:
            # Clean initial state - no scan has been initiated
            st.info("🚀 **Ready to Scan** - Select drives and configuration above, then start scanning to see progress here.")
            
            # Show only basic control button
            action = None
            if st.button("🔄 Reset", key=f"{key_prefix}_reset", disabled=True):
                action = "reset"
            return action
        
        # Status display
        status_col1, status_col2, status_col3 = st.columns([1, 1, 1])
        
        with status_col1:
            self._render_status_indicator()
        
        with status_col2:
            self._render_performance_metrics()
        
        with status_col3:
            self._render_time_info()
        
        # Progress bar
        self._render_progress_bar()
        
        # Control buttons
        action = self._render_control_buttons(key_prefix)
        
        # Current file info
        self._render_current_file_info()
        
        # Detailed statistics
        if st.expander("📊 Detailed Statistics"):
            self._render_detailed_stats()
            
        # Performance chart (if scan is running)
        if self.scan_state['status'] == 'running' and st.expander("📈 Performance Chart"):
            self._render_performance_chart()
        
        return action
    
    def _check_progress_updates(self):
        """Check for progress updates from background scan thread and auto-refresh."""
        if 'progress_queue' in st.session_state:
            # Process all available updates
            updates_received = 0
            while not st.session_state.progress_queue.empty() and updates_received < 10:
                try:
                    update = st.session_state.progress_queue.get_nowait()
                    self.update_progress(update)
                    updates_received += 1
                except:
                    break
            
            # Improved auto-refresh logic for running scans
            if self.scan_state['status'] == 'running':
                current_time = time.time()
                
                # Initialize refresh tracking if not exists
                if 'last_progress_refresh' not in st.session_state:
                    st.session_state.last_progress_refresh = current_time
                    st.session_state.refresh_counter = 0
                
                # Auto-refresh every 3 seconds OR if we have new updates
                time_since_refresh = current_time - st.session_state.last_progress_refresh
                should_refresh = (time_since_refresh > 3.0) or (updates_received > 0)
                
                if should_refresh:
                    st.session_state.last_progress_refresh = current_time
                    st.session_state.refresh_counter = st.session_state.get('refresh_counter', 0) + 1
                    
                    # Prevent infinite loops with counter check
                    if st.session_state.refresh_counter < 500:  # Maximum refresh limit
                        st.rerun()
                        
            # Reset refresh counter when scan is not running
            elif self.scan_state['status'] in ['completed', 'cancelled', 'idle']:
                if 'refresh_counter' in st.session_state:
                    st.session_state.refresh_counter = 0
    
    def _render_status_indicator(self):
        """Render current scan status."""
        status = self.scan_state['status']
        
        status_colors = {
            'idle': '🔵',
            'running': '🟢',
            'paused': '🟡',
            'completed': '✅',
            'cancelled': '🔴'
        }
        
        status_text = {
            'idle': 'Ready',
            'running': 'Scanning...',
            'paused': 'Paused',
            'completed': 'Completed',
            'cancelled': 'Cancelled'
        }
        
        st.markdown(f"""
        **Status**  
        {status_colors.get(status, '❓')} {status_text.get(status, 'Unknown')}
        """)
    
    def _render_performance_metrics(self):
        """Render performance metrics with corrected calculations."""
        elapsed = self.scan_state['elapsed_time']
        files_processed = self.scan_state['files_processed']
        errors = self.scan_state['errors']
        
        # Calculate actual files per second based on real data
        if elapsed > 0 and files_processed > 0:
            fps = files_processed / elapsed
        else:
            fps = 0.0
        
        st.markdown(f"""
        **Performance**  
        🚀 {fps:.1f} files/sec  
        ❌ {errors} errors
        """)
    
    def _render_time_info(self):
        """Render time information with better estimates."""
        elapsed = self.scan_state['elapsed_time']
        eta = self.scan_state['eta']
        files_processed = self.scan_state['files_processed']
        files_per_second = self.scan_state['files_per_second']
        
        # Format elapsed time
        elapsed_str = str(timedelta(seconds=int(elapsed))) if elapsed > 0 else "00:00:00"
        
        # Calculate better ETA
        if eta and eta > 0 and files_processed > 0:
            # Cap ETA at reasonable maximum (24 hours)
            eta_capped = min(eta, 86400)  # 24 hours max
            eta_str = str(timedelta(seconds=int(eta_capped)))
        elif files_per_second > 0 and self.scan_state['total_files'] > files_processed:
            # Calculate ETA based on remaining files and current speed
            remaining_files = self.scan_state['total_files'] - files_processed
            estimated_eta = remaining_files / files_per_second
            estimated_eta = min(estimated_eta, 86400)  # Cap at 24 hours
            eta_str = str(timedelta(seconds=int(estimated_eta)))
        else:
            eta_str = "Calcul en cours..."
        
        st.markdown(f"""
        **Temps**  
        ⏱️ Écoulé: {elapsed_str}  
        🎯 Restant: {eta_str}
        """)
    
    def _render_progress_bar(self):
        """Render stable progress bar with better visual feedback."""
        files_processed = self.scan_state['files_processed']
        total_files = self.scan_state['total_files']
        status = self.scan_state['status']
        
        # Better handling when processed exceeds estimate (don't modify total_files)
        display_total = max(total_files, files_processed) if total_files > 0 else files_processed
            
        # Calculate stable progress percentage
        if total_files > 0:
            progress_percent = min(100.0, (files_processed / display_total) * 100)
            progress_value = min(1.0, files_processed / display_total)
        else:
            # For unlimited scans, show an indeterminate progress
            progress_percent = None  # Will be handled in display
            progress_value = 0.1  # Small progress bar for visual feedback
        
        # Fix completion logic - if we have a limit, check if we reached it
        is_limit_reached = status == 'completed' or (total_files > 0 and files_processed >= total_files)
        
        # Status indicator with corrected logic
        if status == 'running' and not is_limit_reached:
            status_icon = "🔄"
            status_text = "En cours..."
        elif status == 'paused':
            status_icon = "⏸️"
            status_text = "En pause"
        elif status == 'completed' or is_limit_reached:
            status_icon = "✅"
            if is_limit_reached:
                status_text = "Limite atteinte"
            else:
                status_text = "Terminé"
            # Don't force 100% if we reached a file limit
            if total_files > 0:
                progress_percent = min(100.0, (files_processed / total_files) * 100)
                progress_value = min(1.0, files_processed / total_files)
        elif status == 'cancelled':
            status_icon = "🛑"
            status_text = "Annulé"
        else:
            status_icon = "⏳"
            status_text = "Préparation..."
        
        # Main progress display
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if total_files > 0:
                st.progress(progress_value, text=f"{status_icon} {status_text} - {files_processed:,} / {display_total:,} fichiers")
            else:
                st.progress(progress_value, text=f"{status_icon} {status_text} - {files_processed:,} fichiers traités")
        
        with col2:
            if progress_percent is not None:
                st.metric("Progression", f"{progress_percent:.1f}%")
            else:
                st.metric("Fichiers", f"{files_processed:,}")
        
        # Current path info
        current_path = self.scan_state.get('current_path', '')
        if current_path:
            st.caption(f"📁 Répertoire: {current_path}")
    
    def _render_control_buttons(self, key_prefix: str) -> str:
        """Render control buttons (pause, resume, stop)."""
        status = self.scan_state['status']
        
        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
        
        action = None
        
        with col1:
            if status == 'running':
                if st.button("⏸️ Pause", key=f"{key_prefix}_pause"):
                    action = "pause"
            elif status == 'paused':
                if st.button("▶️ Resume", key=f"{key_prefix}_resume"):
                    action = "resume"
            else:
                st.button("⏸️ Pause", key=f"{key_prefix}_pause", disabled=True)
        
        with col2:
            if status in ['running', 'paused']:
                if st.button("⏹️ Stop", key=f"{key_prefix}_stop"):
                    action = "stop"
            else:
                st.button("⏹️ Stop", key=f"{key_prefix}_stop", disabled=True)
        
        with col3:
            if status in ['completed', 'cancelled']:
                if st.button("🔄 Reset", key=f"{key_prefix}_reset"):
                    action = "reset"
            else:
                st.button("🔄 Reset", key=f"{key_prefix}_reset", disabled=True)
        
        with col4:
            # Real-time status indicator
            if status == 'running':
                st.markdown("🔄 **Mise à jour automatique**")
                st.caption("🔴 LIVE - Temps réel")
            elif status == 'paused':
                st.markdown("⏸️ **En pause**")
                st.caption("⏸️ Scan suspendu")
            elif status == 'completed':
                st.markdown("✅ **Terminé**")
                st.caption("🏁 Scan complet")
            elif status == 'cancelled':
                st.markdown("🛑 **Annulé**")
                st.caption("❌ Scan arrêté")
            else:
                st.markdown("⏳ **En attente**")
                st.caption("🔵 Prêt à démarrer")
        
        return action
    
    def _render_current_file_info(self):
        """Render current file being processed with better formatting."""
        current_file = self.scan_state['current_file']
        
        if current_file and self.scan_state['status'] in ['running', 'paused']:
            st.markdown("### 📄 Fichier en Cours de Traitement")
            
            # Better file path formatting
            if len(current_file) > 100:
                # Split path intelligently
                parts = current_file.split('\\')
                if len(parts) > 3:
                    display_file = f"...\\{parts[-3]}\\{parts[-2]}\\{parts[-1]}"
                else:
                    display_file = "..." + current_file[-97:]
            else:
                display_file = current_file
            
            # Show in a container with better styling
            with st.container():
                col1, col2 = st.columns([1, 8])
                with col1:
                    st.markdown("📂")
                with col2:
                    st.markdown(f"**{display_file}**")
                
                # Show file info if available
                try:
                    from pathlib import Path
                    file_path = Path(current_file)
                    if file_path.exists():
                        stat = file_path.stat()
                        size_mb = stat.st_size / (1024 * 1024)
                        st.caption(f"📊 Taille: {size_mb:.2f} MB • Extension: {file_path.suffix}")
                except:
                    st.caption("📁 Analyse en cours...")
        
        elif self.scan_state['status'] == 'completed':
            # Check if we actually completed or just reached the limit
            files_processed = self.scan_state['files_processed']
            total_files = self.scan_state['total_files']
            
            if total_files > 0 and files_processed >= total_files:
                st.success(f"✅ Limite de fichiers atteinte: {files_processed:,} fichiers traités")
            else:
                st.success(f"✅ Scan terminé avec succès: {files_processed:,} fichiers traités")
        elif self.scan_state['status'] == 'cancelled':
            files_processed = self.scan_state['files_processed']
            st.error(f"🛑 Scan annulé par l'utilisateur ({files_processed:,} fichiers traités)")
        elif self.scan_state['status'] == 'paused':
            st.warning("⏸️ Scan en pause - cliquez sur Resume pour continuer")
        
    def _render_detailed_stats(self):
        """Render detailed scanning statistics."""
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("**📊 File Statistics**")
            st.write(f"Total files found: {self.scan_state['total_files']:,}")
            st.write(f"Files processed: {self.scan_state['files_processed']:,}")
            st.write(f"Processing rate: {self.scan_state['files_per_second']:.1f}/sec")
            st.write(f"Errors encountered: {self.scan_state['errors']}")
            
            # Calculate success rate
            processed = self.scan_state['files_processed']
            errors = self.scan_state['errors']
            total_attempted = processed + errors
            if total_attempted > 0:
                success_rate = (processed / total_attempted) * 100
                st.write(f"Success rate: {success_rate:.1f}%")
        
        with col2:
            st.markdown("**⏱️ Time Analysis**")
            start_time = self.scan_state['start_time']
            if start_time:
                st.write(f"Started: {start_time.strftime('%H:%M:%S')}")
            st.write(f"Elapsed: {timedelta(seconds=int(self.scan_state['elapsed_time']))}")
            if self.scan_state['eta']:
                st.write(f"Estimated finish: {(datetime.now() + timedelta(seconds=self.scan_state['eta'])).strftime('%H:%M:%S')}")
            
            # Calculate average time per file
            elapsed = self.scan_state['elapsed_time']
            processed = self.scan_state['files_processed']
            if elapsed > 0 and processed > 0:
                avg_time_per_file = elapsed / processed
                st.write(f"Avg time/file: {avg_time_per_file:.3f}s")
        
        with col3:
            st.markdown("**📈 Performance Metrics**")
            current_path = self.scan_state.get('current_path', '')
            if current_path:
                display_path = (
                    current_path.split('/')[-1]
                    if '/' in current_path
                    else current_path.split('\\')[-1]
                    if '\\' in current_path
                    else current_path
                )
                st.write(f"Current path: {display_path}")
            
            # Progress percentage
            progress = self.scan_state['progress'] * 100
            st.write(f"Completion: {progress:.1f}%")
            
            # Remaining files (handle case where processed > total)
            remaining = max(0, self.scan_state['total_files'] - self.scan_state['files_processed'])
            if remaining > 0:
                st.write(f"Remaining: {remaining:,} files")
            else:
                st.write("Remaining: Scan completed")
            
            # Performance indicator
            fps = self.scan_state['files_per_second']
            if fps > 50:
                perf_indicator = "🚀 Excellent"
            elif fps > 20:
                perf_indicator = "⚡ Good"
            elif fps > 5:
                perf_indicator = "🔄 Normal"
            else:
                perf_indicator = "🐌 Slow"
            st.write(f"Performance: {perf_indicator}")
    
    def _render_performance_chart(self):
        """Render real-time performance chart."""
        try:
            import pandas as pd
            import plotly.express as px
            
            # Create sample data for performance tracking
            elapsed = self.scan_state['elapsed_time']
            if elapsed < 10:  # Not enough data yet
                st.info("⏳ Gathering performance data...")
                return
            
            # Create time series data (simplified for demo)
            time_points = list(range(0, int(elapsed), max(1, int(max(elapsed, 1)/20))))
            files_processed = [
                int((t / max(elapsed, 0.001)) * self.scan_state['files_processed']) 
                for t in time_points
            ]
            
            # Create DataFrame
            df = pd.DataFrame({
                'Time (seconds)': time_points,
                'Files Processed': files_processed,
                'Rate (files/sec)': [
                    files_processed[i] / time_points[i] if time_points[i] > 0 else 0 
                    for i in range(len(time_points))
                ]
            })
            
            # Create charts
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**📈 Files Processed Over Time**")
                fig1 = px.line(df, x='Time (seconds)', y='Files Processed', 
                              title="Cumulative Files Processed")
                fig1.update_layout(height=300)
                st.plotly_chart(fig1, use_container_width=True)
            
            with col2:
                st.markdown("**⚡ Processing Rate**")
                fig2 = px.line(df, x='Time (seconds)', y='Rate (files/sec)',
                              title="Files per Second")
                fig2.update_layout(height=300)
                st.plotly_chart(fig2, use_container_width=True)
                
        except ImportError:
            st.warning("📊 Performance chart requires pandas and plotly packages")
        except Exception as e:
            st.error(f"Chart error: {e}")
    
    def update_progress(self, progress_data: Dict[str, Any]):
        """Update scan progress from scanner engine with improved handling."""
        self.scan_state.update(progress_data)
        
        # Calculate derived metrics
        if progress_data.get('start_time') and self.scan_state['status'] == 'running':
            self.scan_state['elapsed_time'] = (datetime.now() - progress_data['start_time']).total_seconds()
            
            # Calculate ETA with better logic
            files_processed = self.scan_state.get('files_processed', 0)
            files_per_second = self.scan_state.get('files_per_second', 0)
            total_files = self.scan_state.get('total_files', 0)
            
            if files_processed > 0 and files_per_second > 0 and total_files > files_processed:
                remaining_files = total_files - files_processed
                self.scan_state['eta'] = remaining_files / files_per_second
            else:
                self.scan_state['eta'] = None
            
            # Update progress percentage correctly
            if total_files > 0:
                self.scan_state['progress'] = min(1.0, files_processed / total_files)
            else:
                self.scan_state['progress'] = 0.0
    
    def reset_progress(self):
        """Reset progress to initial state."""
        self.scan_state = {
            'status': 'idle',
            'progress': 0.0,
            'current_file': '',
            'files_processed': 0,
            'total_files': 0,
            'files_per_second': 0.0,
            'start_time': None,
            'elapsed_time': 0,
            'eta': None,
            'current_path': '',
            'errors': 0
        }
    
    def get_status(self) -> str:
        """Get current scan status."""
        return self.scan_state['status']
    
    def set_status(self, status: str):
        """Set scan status."""
        self.scan_state['status'] = status
        
        if status == 'running' and not self.scan_state['start_time']:
            self.scan_state['start_time'] = datetime.now()