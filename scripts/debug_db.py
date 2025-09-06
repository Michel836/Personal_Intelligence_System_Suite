"""Debug database content."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager

def debug_database():
    """Debug database content."""
    
    print("🔍 Database Debug")
    print("=" * 40)
    
    db = DatabaseManager()
    
    # Check if database exists and has data
    stats = db.get_statistics()
    print(f"📄 Total files: {stats['total_files']:,}")
    print(f"💾 Total size: {stats['total_gb']:.2f} GB")
    
    if stats['total_files'] == 0:
        print("❌ Database is empty! Run indexing first:")
        print("   python scripts\\full_index.py C: 5000")
        return
    
    # Show some sample files
    print("\n📁 Sample files:")
    results = db.search_files(limit=10)
    for i, result in enumerate(results[:5], 1):
        print(f"{i}. {result['filename']} ({result['file_type']})")
    
    # Test search
    print("\n🔍 Testing search for 'txt':")
    results = db.search_files(query="txt", limit=5)
    print(f"Found {len(results)} results:")
    for result in results:
        print(f"  - {result['filename']}")
    
    # Test by extension
    print("\n📎 Testing search by extension '.py':")
    results = db.search_files(extension=".py", limit=5)
    print(f"Found {len(results)} Python files:")
    for result in results:
        print(f"  - {result['filename']}")
    
    print(f"\n✅ Database location: {db.db_path}")

if __name__ == "__main__":
    debug_database()