"""36TB Intelligence - LITE MODE - Ultra-fast minimal version"""

import streamlit as st
import sqlite3
from pathlib import Path
import time
import os
from typing import List, Dict, Optional

# Minimal imports for speed
st.set_page_config(
    page_title="36TB Intelligence LITE",
    page_icon="⚡",
    layout="wide"
)

class LiteDatabase:
    """Minimal database handler - no ORM, direct SQL for speed."""
    
    def __init__(self, db_path: str = "data/indexes/files.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
    
    def _init_tables(self):
        """Create minimal tables if not exist."""
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                extension TEXT,
                size_bytes INTEGER,
                modified_at TIMESTAMP,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_filename ON files(filename)')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_extension ON files(extension)')
        self.conn.commit()
    
    def search_files(self, query: str, limit: int = 100) -> List[Dict]:
        """Simple filename search."""
        cursor = self.conn.execute(
            """SELECT * FROM files 
               WHERE filename LIKE ? OR path LIKE ?
               ORDER BY modified_at DESC
               LIMIT ?""",
            (f'%{query}%', f'%{query}%', limit)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict:
        """Get basic statistics."""
        cursor = self.conn.execute("""
            SELECT 
                COUNT(*) as total_files,
                SUM(size_bytes) as total_size,
                COUNT(DISTINCT extension) as file_types
            FROM files
        """)
        return dict(cursor.fetchone())
    
    def insert_file(self, file_path: str) -> bool:
        """Insert a single file."""
        try:
            path = Path(file_path)
            if not path.exists():
                return False
            
            stat = path.stat()
            self.conn.execute("""
                INSERT OR REPLACE INTO files (path, filename, extension, size_bytes, modified_at)
                VALUES (?, ?, ?, ?, datetime(?, 'unixepoch'))
            """, (
                str(path.absolute()),
                path.name,
                path.suffix.lower() if path.suffix else None,
                stat.st_size,
                stat.st_mtime
            ))
            self.conn.commit()
            return True
        except Exception:
            return False

class LiteScanner:
    """Minimal file scanner - no threading, simple and fast."""
    
    def __init__(self, db: LiteDatabase):
        self.db = db
        self.is_scanning = False
        self.files_scanned = 0
    
    def scan_directory(self, path: str, max_files: int = 10000) -> int:
        """Scan a directory (non-recursive by default for speed)."""
        self.is_scanning = True
        self.files_scanned = 0
        
        try:
            for entry in os.scandir(path):
                if self.files_scanned >= max_files:
                    break
                
                if entry.is_file():
                    if self.db.insert_file(entry.path):
                        self.files_scanned += 1
                        
                        # Update UI every 100 files
                        if self.files_scanned % 100 == 0:
                            st.write(f"Scanned: {self.files_scanned} files...")
        finally:
            self.is_scanning = False
        
        return self.files_scanned

def main():
    """Main LITE application - minimal and fast."""
    
    st.title("⚡ 36TB Intelligence LITE")
    st.caption("Ultra-fast minimal version - Core features only")
    
    # Initialize minimal components
    if 'db' not in st.session_state:
        st.session_state.db = LiteDatabase()
    
    if 'scanner' not in st.session_state:
        st.session_state.scanner = LiteScanner(st.session_state.db)
    
    # Simple stats bar
    stats = st.session_state.db.get_stats()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Files", f"{stats['total_files']:,}")
    with col2:
        size_mb = (stats['total_size'] or 0) / (1024*1024)
        st.metric("Size", f"{size_mb:.1f} MB")
    with col3:
        st.metric("Types", stats['file_types'])
    
    # Tabs for main features
    tab1, tab2, tab3 = st.tabs(["🔍 Search", "📁 Quick Scan", "📊 Info"])
    
    with tab1:
        # Search interface
        query = st.text_input("Search files:", placeholder="Enter filename...")
        
        if query:
            start_time = time.time()
            results = st.session_state.db.search_files(query, limit=100)
            search_time = time.time() - start_time
            
            st.caption(f"Found {len(results)} results in {search_time:.3f}s")
            
            if results:
                # Simple results table
                for i, file in enumerate(results[:50]):  # Show max 50
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        st.text(file['filename'])
                    with col2:
                        size_kb = file['size_bytes'] / 1024
                        st.text(f"{size_kb:.1f} KB")
                    with col3:
                        if st.button("📂", key=f"open_{i}", help=file['path']):
                            os.startfile(os.path.dirname(file['path']))
            else:
                st.info("No files found")
    
    with tab2:
        # Quick scan interface
        st.subheader("Quick Directory Scan")
        
        # Common folders for quick access
        quick_folders = {
            "Documents": str(Path.home() / "Documents"),
            "Downloads": str(Path.home() / "Downloads"),
            "Desktop": str(Path.home() / "Desktop"),
            "Pictures": str(Path.home() / "Pictures"),
        }
        
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_folder = st.selectbox(
                "Select folder:",
                options=list(quick_folders.values()),
                format_func=lambda x: [k for k, v in quick_folders.items() if v == x][0]
            )
        
        with col2:
            max_files = st.number_input("Max files:", value=1000, min_value=100, max_value=10000)
        
        if st.button("⚡ Quick Scan", type="primary", disabled=st.session_state.scanner.is_scanning):
            with st.spinner(f"Scanning {selected_folder}..."):
                start_time = time.time()
                count = st.session_state.scanner.scan_directory(selected_folder, max_files)
                scan_time = time.time() - start_time
                
                st.success(f"✅ Scanned {count} files in {scan_time:.1f}s")
                st.rerun()
        
        # Custom path
        custom_path = st.text_input("Or enter custom path:")
        if custom_path and st.button("Scan Custom Path"):
            if Path(custom_path).exists():
                with st.spinner(f"Scanning {custom_path}..."):
                    count = st.session_state.scanner.scan_directory(custom_path, max_files)
                    st.success(f"✅ Scanned {count} files")
                    st.rerun()
            else:
                st.error("Path does not exist")
    
    with tab3:
        # System info
        st.subheader("System Information")
        
        # File type distribution
        cursor = st.session_state.db.conn.execute("""
            SELECT extension, COUNT(*) as count
            FROM files
            WHERE extension IS NOT NULL
            GROUP BY extension
            ORDER BY count DESC
            LIMIT 10
        """)
        
        extensions = cursor.fetchall()
        if extensions:
            st.markdown("**Top File Types:**")
            for ext in extensions:
                st.text(f"{ext['extension']}: {ext['count']} files")
        
        # Recent files
        st.markdown("**Recently Modified:**")
        cursor = st.session_state.db.conn.execute("""
            SELECT filename, modified_at
            FROM files
            ORDER BY modified_at DESC
            LIMIT 10
        """)
        
        for file in cursor.fetchall():
            st.text(f"• {file['filename']}")
        
        # Performance metrics
        st.markdown("**Performance:**")
        import psutil
        process = psutil.Process()
        st.text(f"Memory: {process.memory_info().rss / (1024*1024):.1f} MB")
        st.text(f"CPU: {psutil.cpu_percent():.1f}%")
    
    # Minimal footer
    st.markdown("---")
    st.caption("⚡ LITE Mode - Optimized for speed with minimal resources")

if __name__ == "__main__":
    main()