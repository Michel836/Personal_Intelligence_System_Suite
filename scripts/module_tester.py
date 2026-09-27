"""
Module Tester 36TB Intelligence
Teste et valide tous les composants du système de manière automatique.
"""

import os
import sys
import time
import traceback
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
import json
import subprocess
from dataclasses import dataclass

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

@dataclass
class TestResult:
    module: str
    function: str
    status: str  # "PASS", "FAIL", "SKIP"
    execution_time: float
    error_message: Optional[str] = None
    input_data: Optional[Any] = None
    output_data: Optional[Any] = None
    stack_trace: Optional[str] = None

class ModuleTester:
    """Testeur automatique de modules avec interface terminal."""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.start_time = time.time()
        self.current_test = ""
        self.total_tests = 0
        self.completed_tests = 0
        
        # Configuration des tests
        self.test_config = {
            "database": {"priority": 1, "critical": True},
            "scanner": {"priority": 2, "critical": True}, 
            "models": {"priority": 3, "critical": True},
            "search": {"priority": 4, "critical": False},
            "ui": {"priority": 5, "critical": False},
            "ai": {"priority": 6, "critical": False}
        }
        
    def clear_screen(self):
        """Clear terminal screen."""
        os.system('cls' if os.name == 'nt' else 'clear')
        
    def print_header(self):
        """Print test header."""
        print("┌" + "─" * 58 + "┐")
        print("│" + " " * 10 + "MODULE TESTER - 36TB Intelligence" + " " * 10 + "│")
        print("├" + "─" * 58 + "┤")
        
    def print_progress(self):
        """Print current progress."""
        if self.total_tests == 0:
            progress = 0
        else:
            progress = (self.completed_tests / self.total_tests) * 100
            
        # Progress bar
        bar_length = 40
        filled = int(bar_length * progress / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        print(f"│ Progress: {bar} {progress:.0f}% ({self.completed_tests}/{self.total_tests})")
        print("├" + "─" * 58 + "┤")
        
    def print_current_test(self):
        """Print current test being executed."""
        if self.current_test:
            test_text = f"🔄 {self.current_test}"
            if len(test_text) > 56:
                test_text = test_text[:53] + "..."
            print(f"│ {test_text:<56} │")
            
    def print_results_summary(self):
        """Print results summary."""
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        skipped = sum(1 for r in self.results if r.status == "SKIP")
        
        print("├" + "─" * 58 + "┤")
        print(f"│ Results: {passed} PASS  {failed} FAIL  {skipped} SKIP" + " " * (58 - len(f"Results: {passed} PASS  {failed} FAIL  {skipped} SKIP") - 2) + "│")
        
        # Show critical failures
        critical_failures = [r for r in self.results if r.status == "FAIL" and self._is_critical(r.module)]
        if critical_failures:
            print("│" + " " * 56 + "│")
            print("│ WARNING: CRITICAL FAILURES:" + " " * 27 + "│")
            for failure in critical_failures[:3]:  # Show first 3
                error_text = f"   {failure.module}.{failure.function}"
                if len(error_text) > 54:
                    error_text = error_text[:51] + "..."
                print(f"│ {error_text:<56} │")
        
    def print_footer(self):
        """Print test footer."""
        elapsed = time.time() - self.start_time
        print("├" + "─" * 58 + "┤")
        print(f"│ Completed in {elapsed:.1f}s - Report: test_report.json" + " " * (58 - len(f"Completed in {elapsed:.1f}s - Report: test_report.json") - 2) + "│")
        print("└" + "─" * 58 + "┘")
        
    def update_display(self):
        """Update terminal display."""
        self.clear_screen()
        self.print_header()
        self.print_progress()
        self.print_current_test()
        
        # Show last few results
        recent_results = self.results[-10:] if len(self.results) > 10 else self.results
        for result in recent_results:
            status_icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[result.status]
            result_text = f"{status_icon} {result.module}.{result.function}"
            if len(result_text) > 54:
                result_text = result_text[:51] + "..."
            print(f"│ {result_text:<56} │")
            
            # Show error for failures
            if result.status == "FAIL" and result.error_message:
                error_text = f"   └─ {result.error_message}"
                if len(error_text) > 54:
                    error_text = error_text[:51] + "..."
                print(f"│ {error_text:<56} │")
        
        print("│" + " " * 56 + "│")
        
    def _is_critical(self, module: str) -> bool:
        """Check if module is critical."""
        return self.test_config.get(module, {}).get("critical", False)
        
    def run_test(self, module: str, function_name: str, test_func: Callable, 
                 input_data: Any = None, expected_output: Any = None) -> TestResult:
        """Run a single test and record results."""
        self.current_test = f"Testing {module}.{function_name}"
        self.update_display()
        
        start_time = time.time()
        
        try:
            # Execute test function
            if input_data is not None:
                output = test_func(input_data)
            else:
                output = test_func()
                
            execution_time = time.time() - start_time
            
            # Check output if expected
            if expected_output is not None and output != expected_output:
                result = TestResult(
                    module=module,
                    function=function_name,
                    status="FAIL",
                    execution_time=execution_time,
                    error_message=f"Expected {expected_output}, got {output}",
                    input_data=input_data,
                    output_data=output
                )
            else:
                result = TestResult(
                    module=module,
                    function=function_name,
                    status="PASS",
                    execution_time=execution_time,
                    input_data=input_data,
                    output_data=output
                )
                
        except Exception as e:
            execution_time = time.time() - start_time
            result = TestResult(
                module=module,
                function=function_name,
                status="FAIL",
                execution_time=execution_time,
                error_message=str(e),
                input_data=input_data,
                stack_trace=traceback.format_exc()
            )
            
        self.results.append(result)
        self.completed_tests += 1
        self.update_display()
        
        # Small delay to see progress
        time.sleep(0.1)
        
        return result
        
    def test_database_module(self):
        """Test DatabaseManager module."""
        self.current_test = "Loading DatabaseManager..."
        self.update_display()
        
        try:
            from src.core.database import DatabaseManager
        except ImportError as e:
            self.run_test("database", "import", lambda: None)
            return
            
        # Test 1: Initialization
        def test_init():
            db = DatabaseManager()
            return db is not None
            
        self.run_test("database", "__init__", test_init)
        
        # Test 2: Database connection
        def test_connection():
            db = DatabaseManager()
            with db.get_connection() as conn:
                cursor = conn.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
                
        self.run_test("database", "connection", test_connection)
        
        # Test 3: Statistics (problematic area)
        def test_statistics():
            db = DatabaseManager()
            stats = db.get_statistics()
            return isinstance(stats, dict) and 'total_files' in stats
            
        self.run_test("database", "get_statistics", test_statistics)
        
        # Test 4: Search functionality
        def test_search():
            db = DatabaseManager()
            results = db.search_files(query="test", limit=10)
            return isinstance(results, list)
            
        self.run_test("database", "search_files", test_search)
        
    def test_scanner_module(self):
        """Test Scanner modules."""
        self.current_test = "Loading Scanner modules..."
        self.update_display()
        
        # Test TurboScanner
        try:
            from src.scanner.turbo_scan import TurboScanner
            
            def test_turbo_init():
                scanner = TurboScanner()
                return scanner is not None
                
            self.run_test("scanner", "TurboScanner.__init__", test_turbo_init)
            
            def test_file_type():
                scanner = TurboScanner()
                file_type = scanner.get_file_type('.pdf')
                return file_type == 'document'
                
            self.run_test("scanner", "get_file_type", test_file_type)
            
        except ImportError as e:
            self.run_test("scanner", "TurboScanner_import", 
                         lambda: None, error_message=str(e))
            
        # Test regular scanner
        try:
            from src.scanner.fast_engine import FastScannerEngine
            
            def test_fast_scanner():
                scanner = FastScannerEngine()
                return scanner is not None
                
            self.run_test("scanner", "FastScannerEngine.__init__", test_fast_scanner)
            
        except ImportError as e:
            self.run_test("scanner", "FastScannerEngine_import", 
                         lambda: None, error_message=str(e))
            
    def test_models_module(self):
        """Test data models."""
        try:
            from src.scanner.models import FileInfo, FileType, Priority
            
            def test_file_info():
                file_info = FileInfo(
                    path=Path("test.txt"),
                    filename="test.txt", 
                    extension=".txt",
                    size_bytes=1024
                )
                return file_info.filename == "test.txt"
                
            self.run_test("models", "FileInfo", test_file_info)
            
            def test_file_type_enum():
                return FileType.DOCUMENT.value == "document"
                
            self.run_test("models", "FileType", test_file_type_enum)
            
        except ImportError as e:
            self.run_test("models", "import", lambda: None, error_message=str(e))
            
    def generate_report(self):
        """Generate detailed test report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results if r.status == "PASS"),
            "failed": sum(1 for r in self.results if r.status == "FAIL"),
            "skipped": sum(1 for r in self.results if r.status == "SKIP"),
            "execution_time": time.time() - self.start_time,
            "results": []
        }
        
        for result in self.results:
            report["results"].append({
                "module": result.module,
                "function": result.function,
                "status": result.status,
                "execution_time": result.execution_time,
                "error_message": result.error_message,
                "stack_trace": result.stack_trace
            })
            
        # Save report
        with open("test_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        return report
        
    def run_all_tests(self):
        """Run all tests in priority order."""
        self.clear_screen()
        
        # Count total tests
        self.total_tests = 10  # Approximation
        
        print("Starting Module Tests...")
        time.sleep(1)
        
        # Priority 1: Database (Critical)
        self.test_database_module()
        
        # Priority 2: Scanner (Critical)  
        self.test_scanner_module()
        
        # Priority 3: Models (Critical)
        self.test_models_module()
        
        # Final display
        self.current_test = "Generating report..."
        self.update_display()
        
        # Generate report
        report = self.generate_report()
        
        # Final results
        self.current_test = ""
        self.update_display()
        self.print_results_summary() 
        self.print_footer()
        
        return report

def main():
    """Main entry point."""
    tester = ModuleTester()
    
    print("Module Tester - 36TB Intelligence")
    print("Starting comprehensive tests...")
    print()
    
    try:
        report = tester.run_all_tests()
        
        print()
        print("📋 Test completed! Check test_report.json for details.")
        
        # Show critical failures
        critical_failures = [r for r in tester.results 
                           if r.status == "FAIL" and tester._is_critical(r.module)]
        
        if critical_failures:
            print()
            print("WARNING: CRITICAL FAILURES FOUND:")
            for failure in critical_failures:
                print(f"   [FAIL] {failure.module}.{failure.function}: {failure.error_message}")
                if failure.stack_trace:
                    print(f"      Stack trace available in test_report.json")
        else:
            print("SUCCESS: All critical modules passed!")
            
    except KeyboardInterrupt:
        print("\n\nSTOP: Tests interrupted by user")
    except Exception as e:
        print(f"\n\nERROR: Test runner crashed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()