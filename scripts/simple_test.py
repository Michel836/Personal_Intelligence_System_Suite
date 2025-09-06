"""Simple test without complex configuration."""

import sys
import time
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.scanner.models import FileInfo, FileType, Priority
from src.scanner.engine import ScannerEngine
from src.core.logging import setup_logging

# Setup logging
setup_logging()

def simple_scan_test():
    """Simple scan test."""
    
    print("🔍 Simple Scan Test")
    print("=" * 40)
    
    # Get drive from command line
    drive = sys.argv[1] if len(sys.argv) > 1 else "C:"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    
    scan_path = Path(drive + "\\") if not drive.endswith("\\") else Path(drive)
    
    if not scan_path.exists():
        print(f"❌ Drive {drive} not found!")
        return
    
    print(f"📁 Scanning: {scan_path}")
    print(f"📊 Limit: {limit:,} files")
    print()
    
    # Create scanner
    scanner = ScannerEngine(max_workers=4)
    results = []
    
    start_time = time.time()
    
    try:
        # Simple progress display
        for i, file_info in enumerate(scanner.scan_paths([scan_path], limit=limit)):
            results.append(file_info)
            
            if i % 100 == 0 and i > 0:
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                print(f"📄 Progress: {i:,} files ({rate:.0f} files/sec)")
    
    except KeyboardInterrupt:
        print("\n⏹️  Scan interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")
        return
    
    # Results
    scan_time = time.time() - start_time
    
    if results:
        total_size = sum(f.size_bytes for f in results) / (1024**3)
        
        print(f"\n✅ Scan Complete!")
        print(f"📄 Files: {len(results):,}")
        print(f"💾 Size: {total_size:.2f} GB")
        print(f"⏱️  Time: {scan_time:.1f}s")
        print(f"🚀 Speed: {len(results)/scan_time:.0f} files/sec")
        
        # File types
        type_counts = {}
        for f in results:
            type_counts[f.file_type.value] = type_counts.get(f.file_type.value, 0) + 1
        
        print(f"\n📊 File Types:")
        for ftype, count in sorted(type_counts.items()):
            print(f"  {ftype}: {count:,}")
    
    else:
        print("❌ No files found!")

if __name__ == "__main__":
    simple_scan_test()