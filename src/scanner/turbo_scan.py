"""Ultra-fast scanner for massive volumes - 36TB Intelligence."""

import os
import sqlite3
from pathlib import Path
import time
from datetime import datetime
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from src.core.database import DatabaseManager
from .models import FileInfo, FileType, stat_created_at
from loguru import logger

class TurboScanner:
    """Ultra-fast scanner optimized for massive volumes."""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.files_queue = queue.Queue(maxsize=50000)
        self.volume_id = None
        self.scan_id = None
        self.stats = {
            'files_found': 0,
            'files_saved': 0,
            'total_size': 0,
            'start_time': time.time()
        }

    def set_scan_context(self, volume_id, scan_id):
        """Attach the current volume/scan-run so persistence is lifecycle-aware."""
        self.volume_id = volume_id
        self.scan_id = scan_id
        
    def fast_directory_walk(self, root_path, file_queue, exclude_dirs=None):
        """Ultra-fast directory walker with minimal I/O."""
        if exclude_dirs is None:
            exclude_dirs = {
                'System Volume Information', '$Recycle.Bin', 'Windows', 
                'Program Files', 'Program Files (x86)', 'ProgramData',
                '.git', '__pycache__', 'node_modules', '.vscode', '.vs',
                'Temp', 'tmp', 'AppData', 'Recovery'
            }
        
        try:
            with os.scandir(root_path) as entries:
                dirs_to_process = []
                
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            # Only get essential info - no content reading!
                            stat_info = entry.stat()
                            
                            file_info = {
                                'path': str(Path(entry.path)),
                                'filename': entry.name,
                                'size_bytes': stat_info.st_size,
                                'modified_at': datetime.fromtimestamp(stat_info.st_mtime),
                                'created_at': stat_created_at(stat_info),
                                'device_id': stat_info.st_dev,
                                'inode': stat_info.st_ino,
                            }
                            
                            # Add to queue
                            file_queue.put(file_info)
                            self.stats['files_found'] += 1
                            self.stats['total_size'] += stat_info.st_size
                            
                            # Progress every 10000 files
                            if self.stats['files_found'] % 10000 == 0:
                                elapsed = time.time() - self.stats['start_time']
                                files_per_sec = self.stats['files_found'] / max(elapsed, 0.001)
                                size_gb = self.stats['total_size'] / (1024**3)
                                
                                print(f"Files: {self.stats['files_found']:,} | "
                                      f"Size: {size_gb:.1f} GB | "
                                      f"Speed: {files_per_sec:.0f} files/sec")
                        
                        elif entry.is_dir(follow_symlinks=False):
                            dir_name = entry.name
                            if dir_name not in exclude_dirs and not dir_name.startswith('.'):
                                dirs_to_process.append(entry.path)
                                
                    except (OSError, PermissionError):
                        continue  # Skip inaccessible files/dirs
                
                # Process subdirectories
                for dir_path in dirs_to_process:
                    try:
                        self.fast_directory_walk(dir_path, file_queue, exclude_dirs)
                    except (OSError, PermissionError):
                        continue
                        
        except (OSError, PermissionError):
            pass
    
    def batch_saver(self, file_queue, batch_size=5000):
        """Convert queued entries to FileInfo and save in large batches."""
        batch = []

        while True:
            try:
                # Get file from queue
                entry = file_queue.get(timeout=5)

                if entry is None:  # Stop signal
                    # Flush the final partial batch before exiting.
                    if batch:
                        self.save_batch(batch)
                        batch = []
                    break

                ext = Path(entry['filename']).suffix.lower()
                batch.append(FileInfo(
                    path=Path(entry['path']),
                    filename=entry['filename'],
                    extension=ext,
                    size_bytes=entry['size_bytes'],
                    created_at=entry['created_at'],
                    modified_at=entry['modified_at'],
                    device_id=entry.get('device_id'),
                    inode=entry.get('inode'),
                    file_type=FileType(self.get_file_type(ext)),
                ))

                # Save when batch is full
                if len(batch) >= batch_size:
                    self.save_batch(batch)
                    batch = []

                file_queue.task_done()

            except queue.Empty:
                # Save remaining batch
                if batch:
                    self.save_batch(batch)
                    batch = []
                continue
    
    def save_batch(self, files):
        """Persist a batch of FileInfo via the canonical UPSERT contract.

        Delegates to :meth:`DatabaseManager.save_files_batch` so TurboScanner
        shares exactly the same persistence semantics (metadata refresh,
        content preservation, checksum/created_at preservation, FTS triggers).
        """
        if not files:
            return
        try:
            with self.db.get_connection() as conn:
                count_before = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

            self.db.save_files_batch(
                files, volume_id=self.volume_id, scan_id=self.scan_id
            )

            with self.db.get_connection() as conn:
                count_after = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

            self.stats['files_saved'] += count_after - count_before
            self.stats['files_processed'] = self.stats.get('files_processed', 0) + len(files)

            if self.stats['files_processed'] % 50000 == 0:
                elapsed = time.time() - self.stats['start_time']
                print(f"PROCESSED {self.stats['files_processed']:,} files | NEW: {self.stats['files_saved']:,} | TIME: {elapsed:.1f}s")

        except Exception as e:
            logger.error(f"Batch save error: {e}")
    
    def get_file_type(self, extension):
        """Quick file type classification."""
        ext = extension.lower()
        
        if ext in {'.pdf', '.doc', '.docx', '.rtf', '.txt', '.odt'}:
            return 'document'
        elif ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.tiff', '.webp'}:
            return 'image'
        elif ext in {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'}:
            return 'video'
        elif ext in {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma'}:
            return 'audio'
        elif ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}:
            return 'archive'
        elif ext in {'.py', '.js', '.html', '.css', '.cpp', '.java', '.cs'}:
            return 'code'
        elif ext in {'.xls', '.xlsx', '.csv', '.ppt', '.pptx'}:
            return 'document'
        else:
            return 'other'
    
    def turbo_scan(self, scan_path):
        """Ultra-fast scan with threading."""
        print(f"TURBO SCAN STARTING: {scan_path}")
        print("Optimized for massive volumes - NO content extraction!")
        
        # Start batch saver thread
        saver_thread = threading.Thread(
            target=self.batch_saver,
            args=(self.files_queue,),
            daemon=True
        )
        saver_thread.start()
        
        # Start scanning
        scan_start = time.time()
        
        try:
            self.fast_directory_walk(scan_path, self.files_queue)
            
            # Signal completion
            self.files_queue.put(None)
            saver_thread.join(timeout=60)
            
        except KeyboardInterrupt:
            print("\nScan interrupted by user")
            return None
        except Exception as e:
            print(f"\nScan failed with error: {e}")
            return None
        
        scan_duration = time.time() - scan_start
        
        # Final stats with safe calculations
        try:
            final_stats = {
                'files_found': self.stats.get('files_found', 0),
                'files_saved': self.stats.get('files_saved', 0),
                'total_size_bytes': self.stats.get('total_size', 0),
                'total_size_gb': self.stats.get('total_size', 0)/(1024**3),
                'duration': scan_duration,
                'files_per_second': self.stats.get('files_found', 0) / max(scan_duration, 0.001)
            }
        except Exception as e:
            print(f"Error calculating stats: {e}")
            return None
        
        print("\n" + "="*50)
        print("TURBO SCAN COMPLETE!")
        print(f"Files found: {final_stats['files_found']:,}")
        print(f"Files saved: {final_stats['files_saved']:,}")
        print(f"Total size: {final_stats['total_size_gb']:.1f} GB")
        print(f"Duration: {final_stats['duration']:.1f} seconds")
        print(f"Speed: {final_stats['files_per_second']:.0f} files/sec")
        print("="*50)
        
        return final_stats

if __name__ == "__main__":
    # For C: drive - exclude system directories for speed
    scanner = TurboScanner()
    
    print("36TB Intelligence - TURBO SCANNER")
    print("Optimized for massive volumes!")
    
    # Ask for specific path to avoid full C: scan
    print("\nRECOMMENDED: Scan specific directories instead of entire C:")
    print("Examples:")
    print("- C:\\Users\\YourName\\Documents")
    print("- C:\\Users\\YourName\\Desktop")
    print("- D:\\Data")
    
    # Auto-start with Documents folder for faster demo
    username = os.getenv('USERNAME', 'User')
    docs_path = f"C:\\Users\\{username}\\Documents"
    
    if Path(docs_path).exists():
        print(f"\nAuto-starting with: {docs_path}")
        scan_path = docs_path
    else:
        scan_path = input("\nEnter path to scan (or 'C:\\' for full drive): ").strip()
        if not scan_path:
            scan_path = "C:\\"
    
    if not Path(scan_path).exists():
        print(f"ERROR: Path not found: {scan_path}")
        exit(1)
    
    # Confirm for full C: drive
    if scan_path.upper() == "C:\\":
        print("WARNING: Full C: drive scan will take hours.")
        print("Press Ctrl+C to cancel if needed.")
    
    scanner.turbo_scan(scan_path)