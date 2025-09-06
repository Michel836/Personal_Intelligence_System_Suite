"""
Simple Module Tester - 36TB Intelligence
Tests all components with Windows compatibility.
"""

import os
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime
import json

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

class SimpleTester:
    """Simple Windows-compatible module tester."""
    
    def __init__(self):
        self.results = []
        self.start_time = time.time()
        
    def test_result(self, module, function, status, error=None, duration=0):
        """Record a test result."""
        self.results.append({
            "module": module,
            "function": function,
            "status": status,
            "error": error,
            "duration": duration
        })
        
        # Print result immediately
        status_char = "+" if status == "PASS" else "-" if status == "FAIL" else "?"
        print(f"[{status_char}] {module}.{function}")
        if error:
            print(f"    Error: {error}")
            
    def run_test(self, module, function, test_func):
        """Run a single test."""
        print(f"Testing {module}.{function}...")
        start = time.time()
        
        try:
            result = test_func()
            duration = time.time() - start
            
            if result is False:
                self.test_result(module, function, "FAIL", "Function returned False", duration)
            else:
                self.test_result(module, function, "PASS", None, duration)
                
        except Exception as e:
            duration = time.time() - start
            self.test_result(module, function, "FAIL", str(e), duration)
            
    def test_database(self):
        """Test database module."""
        print("\n=== TESTING DATABASE MODULE ===")
        
        # Test 1: Import
        def test_import():
            from src.core.database import DatabaseManager
            return True
            
        self.run_test("database", "import", test_import)
        
        # Test 2: Initialization
        def test_init():
            from src.core.database import DatabaseManager
            db = DatabaseManager()
            return db is not None
            
        self.run_test("database", "init", test_init)
        
        # Test 3: Connection
        def test_connection():
            from src.core.database import DatabaseManager
            db = DatabaseManager()
            with db.get_connection() as conn:
                cursor = conn.execute("SELECT 1")
                result = cursor.fetchone()[0]
                return result == 1
                
        self.run_test("database", "connection", test_connection)
        
        # Test 4: Statistics (problematic!)
        def test_stats():
            from src.core.database import DatabaseManager
            db = DatabaseManager()
            stats = db.get_statistics()
            return isinstance(stats, dict) and 'total_files' in stats
            
        self.run_test("database", "get_statistics", test_stats)
        
        # Test 5: Search
        def test_search():
            from src.core.database import DatabaseManager
            db = DatabaseManager()
            results = db.search_files(query="test", limit=5)
            return isinstance(results, list)
            
        self.run_test("database", "search", test_search)
        
    def test_scanner(self):
        """Test scanner modules."""
        print("\n=== TESTING SCANNER MODULES ===")
        
        # Test TurboScanner
        def test_turbo_import():
            sys.path.append(str(Path(__file__).parent))
            from turbo_scan import TurboScanner
            return True
            
        self.run_test("scanner", "turbo_import", test_turbo_import)
        
        def test_turbo_init():
            sys.path.append(str(Path(__file__).parent))
            from turbo_scan import TurboScanner
            scanner = TurboScanner()
            return scanner is not None
            
        self.run_test("scanner", "turbo_init", test_turbo_init)
        
        def test_file_type():
            sys.path.append(str(Path(__file__).parent))
            from turbo_scan import TurboScanner
            scanner = TurboScanner()
            result = scanner.get_file_type('.pdf')
            return result == 'document'
            
        self.run_test("scanner", "file_type", test_file_type)
        
        # Test regular scanner
        def test_fast_scanner():
            from src.scanner.fast_engine import FastScannerEngine
            scanner = FastScannerEngine()
            return scanner is not None
            
        self.run_test("scanner", "fast_engine", test_fast_scanner)
        
    def test_models(self):
        """Test data models."""
        print("\n=== TESTING MODELS ===")
        
        def test_models_import():
            from src.scanner.models import FileInfo, FileType, Priority
            return True
            
        self.run_test("models", "import", test_models_import)
        
        def test_fileinfo():
            from src.scanner.models import FileInfo, FileType, Priority
            file_info = FileInfo(
                path=Path("test.txt"),
                filename="test.txt",
                extension=".txt", 
                size_bytes=1024
            )
            return file_info.filename == "test.txt"
            
        self.run_test("models", "FileInfo", test_fileinfo)
        
        def test_enums():
            from src.scanner.models import FileType, Priority
            return FileType.DOCUMENT.value == "document"
            
        self.run_test("models", "enums", test_enums)
        
    def test_search_engines(self):
        """Test search functionality."""
        print("\n=== TESTING SEARCH ENGINES ===")
        
        def test_semantic_import():
            from src.intelligence.semantic_search import SemanticSearchEngine
            return True
            
        self.run_test("search", "semantic_import", test_semantic_import)
        
        def test_semantic_init():
            from src.intelligence.semantic_search import SemanticSearchEngine
            engine = SemanticSearchEngine()
            return engine is not None
            
        self.run_test("search", "semantic_init", test_semantic_init)
        
        def test_semantic_search():
            from src.intelligence.semantic_search import SemanticSearchEngine
            engine = SemanticSearchEngine()
            # Test both methods
            results1 = engine.search("test query", limit=5)
            results2 = engine.semantic_search("test query", limit=5)
            return isinstance(results1, list) and isinstance(results2, list)
            
        self.run_test("search", "semantic_methods", test_semantic_search)
        
    def generate_report(self):
        """Generate test report."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        
        print(f"\n=== TEST SUMMARY ===")
        print(f"Total tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Success rate: {(passed/total)*100:.1f}%" if total > 0 else "0%")
        print(f"Duration: {time.time() - self.start_time:.1f}s")
        
        # Show failures
        failures = [r for r in self.results if r["status"] == "FAIL"]
        if failures:
            print(f"\n=== FAILURES ({len(failures)}) ===")
            for failure in failures:
                print(f"FAIL: {failure['module']}.{failure['function']}")
                print(f"  Error: {failure['error']}")
                
        # Save detailed report
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total,
                "passed": passed, 
                "failed": failed,
                "duration": time.time() - self.start_time
            },
            "results": self.results
        }
        
        with open("test_report.json", "w") as f:
            json.dump(report, f, indent=2)
            
        print(f"\nDetailed report saved to: test_report.json")
        
        return failures
        
    def run_all_tests(self):
        """Run all tests."""
        print("Module Tester - 36TB Intelligence")
        print("=" * 50)
        print("Testing fundamental modules...")
        print()
        
        # Core tests (priority order)
        self.test_database()    # Most critical
        self.test_scanner()     # Performance critical
        self.test_models()      # Data structures
        self.test_search_engines()  # Search functionality
        
        # Generate final report
        failures = self.generate_report()
        
        # Return critical failures for analysis
        critical_modules = ["database", "scanner", "models"]
        critical_failures = [f for f in failures if f["module"] in critical_modules]
        
        if critical_failures:
            print(f"\nCRITICAL: {len(critical_failures)} critical failures found!")
            print("System may not function properly.")
        else:
            print("\nSUCCESS: All critical modules passed!")
            
        return failures

def main():
    """Main entry point."""
    tester = SimpleTester()
    
    try:
        failures = tester.run_all_tests()
        
        # Exit with proper code
        if any(f["module"] in ["database", "scanner", "models"] for f in failures):
            print("\nExiting with error code due to critical failures.")
            exit(1)
        else:
            print("\nAll tests completed successfully!")
            exit(0)
            
    except KeyboardInterrupt:
        print("\n\nTesting interrupted by user.")
        exit(2)
    except Exception as e:
        print(f"\n\nTest runner crashed: {e}")
        traceback.print_exc()
        exit(3)

if __name__ == "__main__":
    main()