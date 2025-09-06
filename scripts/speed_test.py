"""Speed test comparison between engines."""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.scanner.fast_engine import FastScannerEngine
from src.core.logging import setup_logging

# Setup minimal logging
setup_logging()

def speed_test():
    """Compare scanner speeds."""
    
    print("🚀 Scanner Speed Test")
    print("=" * 50)
    
    # Get parameters
    drive = sys.argv[1] if len(sys.argv) > 1 else "C:"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    
    scan_path = Path(drive + "\\") if not drive.endswith("\\") else Path(drive)
    
    if not scan_path.exists():
        print(f"❌ Drive {drive} not found!")
        return
    
    print(f"📁 Scanning: {scan_path}")
    print(f"📊 Limit: {limit:,} files")
    print()
    
    # Test Fast Engine
    print("🏎️  Testing FastScannerEngine...")
    fast_scanner = FastScannerEngine()
    results = []
    
    start_time = time.time()
    
    try:
        for i, file_info in enumerate(fast_scanner.fast_scan(scan_path, limit=limit)):
            results.append(file_info)
            
            # Real-time progress every 500 files
            if i > 0 and i % 500 == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                print(f"  📄 Progress: {i:,} files ({rate:.0f} files/sec)")
        
        total_time = time.time() - start_time
        
        if results:
            total_size = sum(f.size_bytes for f in results) / (1024**3)
            rate = len(results) / total_time if total_time > 0 else 0
            throughput = total_size / total_time if total_time > 0 else 0
            
            print(f"\n✅ FastScannerEngine Results:")
            print(f"📄 Files: {len(results):,}")
            print(f"💾 Size: {total_size:.2f} GB")  
            print(f"⏱️  Time: {total_time:.1f}s")
            print(f"🚀 Speed: {rate:.0f} files/sec")
            print(f"📈 Throughput: {throughput:.1f} GB/sec")
            
            # File type breakdown
            type_counts = {}
            for f in results:
                ftype = f.file_type.value
                type_counts[ftype] = type_counts.get(ftype, 0) + 1
            
            print(f"\n📊 File Types:")
            for ftype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / len(results)) * 100
                print(f"  {ftype:10}: {count:,} ({percentage:.1f}%)")
            
            # Priority breakdown
            priority_counts = {}
            for f in results:
                priority = f.priority.value
                priority_counts[priority] = priority_counts.get(priority, 0) + 1
            
            print(f"\n🎯 Priorities:")
            for priority, count in sorted(priority_counts.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / len(results)) * 100
                print(f"  {priority:8}: {count:,} ({percentage:.1f}%)")
                
            # Size distribution
            size_ranges = {"< 1KB": 0, "1KB-1MB": 0, "1MB-10MB": 0, "10MB-100MB": 0, "> 100MB": 0}
            for f in results:
                mb = f.size_bytes / (1024 * 1024)
                kb = f.size_bytes / 1024
                if kb < 1:
                    size_ranges["< 1KB"] += 1
                elif mb < 1:
                    size_ranges["1KB-1MB"] += 1
                elif mb < 10:
                    size_ranges["1MB-10MB"] += 1
                elif mb < 100:
                    size_ranges["10MB-100MB"] += 1
                else:
                    size_ranges["> 100MB"] += 1
            
            print(f"\n📏 Size Distribution:")
            for size_range, count in size_ranges.items():
                if count > 0:
                    percentage = (count / len(results)) * 100
                    print(f"  {size_range:10}: {count:,} ({percentage:.1f}%)")
        
        else:
            print("❌ No files found!")
    
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    speed_test()