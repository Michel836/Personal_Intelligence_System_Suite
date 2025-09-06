"""Quick scan script for testing the scanner engine."""

import sys
import json
import time
from pathlib import Path
from typing import List

from loguru import logger
from rich.console import Console
from rich.progress import Progress, TaskID
from rich.table import Table
from rich.panel import Panel

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.core.config import settings
from src.core.logging import setup_logging
from src.scanner.engine import ScannerEngine
from src.scanner.models import ScanProgress


def progress_callback(progress: ScanProgress) -> None:
    """Update progress display."""
    if hasattr(progress_callback, 'task_id'):
        progress_bar.update(
            progress_callback.task_id,
            completed=progress.scanned_files,
            description=f"Scanning... {progress.current_file or 'Unknown file'}"
        )


def main():
    """Run quick scan test."""
    console = Console()
    
    # Parse arguments
    if len(sys.argv) < 2:
        console.print("[red]Usage: python scripts/quick_scan.py <drive_letter> [limit][/red]")
        console.print("Example: python scripts/quick_scan.py C: 1000")
        sys.exit(1)
    
    drive = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    
    # Setup
    setup_logging()
    scan_path = Path(drive + "\\") if not drive.endswith("\\") else Path(drive)
    
    if not scan_path.exists():
        console.print(f"[red]Drive {drive} not found![/red]")
        sys.exit(1)
    
    console.print(Panel.fit(
        f"🔍 Quick Scan Test\n"
        f"Drive: {drive}\n"
        f"Limit: {limit:,} files\n"
        f"Max workers: {settings.max_workers}",
        title="36TB Intelligence Scanner"
    ))
    
    # Initialize scanner with validation
    scanner = ScannerEngine()
    
    # Validate scan settings
    validation = scanner.validate_scan_settings([scan_path])
    if not validation['valid']:
        for error in validation['errors']:
            console.print(f"[red]❌ {error}[/red]")
        sys.exit(1)
    
    # Show warnings and recommendations
    for warning in validation['warnings']:
        console.print(f"[yellow]⚠️  {warning}[/yellow]")
    for rec in validation['recommendations']:
        console.print(f"[blue]💡 {rec}[/blue]")
    
    results = []
    
    # Global progress bar
    global progress_bar
    with Progress() as progress_bar:
        task_id = progress_bar.add_task("Initializing...", total=limit)
        progress_callback.task_id = task_id
        
        start_time = time.time()
        
        try:
            # Scan files
            for file_info in scanner.scan_paths(
                paths=[scan_path],
                limit=limit,
                include_system=False,
                progress_callback=progress_callback
            ):
                results.append(file_info)
                
                # Update progress display every 100 files
                if len(results) % 100 == 0:
                    console.print(f"📁 Processed: {len(results):,} files")
        
        except KeyboardInterrupt:
            console.print("\n[yellow]Scan interrupted by user[/yellow]")
        except Exception as e:
            console.print(f"[red]Scan error: {e}[/red]")
            logger.exception("Scan failed")
            return
    
    scan_time = time.time() - start_time
    
    # Calculate statistics
    if results:
        stats = scanner._calculate_stats(results)
        
        # Display results
        display_results(console, stats, scan_time)
        
        # Save results
        save_results(stats, drive, limit)
        
    else:
        console.print("[yellow]No files found![/yellow]")


def display_results(console: Console, stats, scan_time: float) -> None:
    """Display scan results in formatted tables."""
    
    # Summary table
    summary_table = Table(title="📊 Scan Summary", show_header=True)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green")
    
    summary_table.add_row("Total Files", f"{stats.total_files:,}")
    summary_table.add_row("Total Size", f"{stats.total_gb:.2f} GB")
    summary_table.add_row("Unique Files", f"{stats.unique_files:,}")
    summary_table.add_row("Duplicates", f"{stats.duplicate_files:,} ({stats.duplicate_percent:.1f}%)")
    summary_table.add_row("Scan Time", f"{scan_time:.1f} seconds")
    summary_table.add_row("Speed", f"{stats.files_per_second:.0f} files/sec")
    summary_table.add_row("Throughput", f"{stats.mb_per_second:.1f} MB/sec")
    
    console.print(summary_table)
    
    # File types table
    if stats.file_types:
        types_table = Table(title="📄 File Types", show_header=True)
        types_table.add_column("Type", style="cyan")
        types_table.add_column("Count", style="green")
        types_table.add_column("Percentage", style="yellow")
        
        for file_type, count in stats.file_types.items():
            percentage = (count / stats.total_files) * 100
            types_table.add_row(
                file_type.title(),
                f"{count:,}",
                f"{percentage:.1f}%"
            )
        
        console.print(types_table)
    
    # Top extensions
    if stats.extensions:
        ext_table = Table(title="📎 Top Extensions", show_header=True)
        ext_table.add_column("Extension", style="cyan")
        ext_table.add_column("Count", style="green")
        
        for ext, count in list(stats.extensions.items())[:10]:
            ext_table.add_row(ext or "(none)", f"{count:,}")
        
        console.print(ext_table)
    
    # Year distribution
    if stats.year_distribution:
        year_table = Table(title="📅 Year Distribution", show_header=True)
        year_table.add_column("Year", style="cyan")
        year_table.add_column("Files", style="green")
        
        # Sort by year, show last 10 years
        sorted_years = sorted(stats.year_distribution.items())[-10:]
        for year, count in sorted_years:
            year_table.add_row(str(year), f"{count:,}")
        
        console.print(year_table)
    
    # Largest files
    if stats.largest_files:
        large_table = Table(title="💾 Largest Files", show_header=True)
        large_table.add_column("File", style="cyan", max_width=50)
        large_table.add_column("Size", style="green")
        
        for file_info in stats.largest_files[:5]:
            large_table.add_row(
                file_info.filename,
                f"{file_info.size_mb:.1f} MB"
            )
        
        console.print(large_table)


def save_results(stats, drive: str, limit: int) -> None:
    """Save scan results to JSON file."""
    
    # Create reports directory
    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare data for JSON serialization
    report_data = {
        "scan_info": {
            "drive": drive,
            "limit": limit,
            "timestamp": stats.scan_duration_seconds,
        },
        "summary": {
            "total_files": stats.total_files,
            "total_gb": stats.total_gb,
            "unique_files": stats.unique_files,
            "duplicate_files": stats.duplicate_files,
            "duplicate_percent": stats.duplicate_percent,
            "scan_duration": stats.scan_duration_seconds,
            "files_per_second": stats.files_per_second,
        },
        "distributions": {
            "file_types": stats.file_types,
            "extensions": stats.extensions,
            "priorities": stats.priorities,
            "size_ranges": stats.size_ranges,
            "year_distribution": stats.year_distribution,
        },
        "top_files": {
            "largest": [
                {
                    "filename": f.filename,
                    "size_mb": f.size_mb,
                    "path": str(f.path)
                }
                for f in stats.largest_files[:10]
            ],
            "oldest": [
                {
                    "filename": f.filename,
                    "modified": f.modified_at.isoformat(),
                    "path": str(f.path)
                }
                for f in stats.oldest_files[:10]
            ],
            "newest": [
                {
                    "filename": f.filename,
                    "modified": f.modified_at.isoformat(),
                    "path": str(f.path)
                }
                for f in stats.newest_files[:10]
            ]
        }
    }
    
    # Save to file
    timestamp = int(time.time())
    drive_clean = drive.replace(":", "").replace("\\", "")
    filename = f"scan_{drive_clean}_{limit}_{timestamp}.json"
    filepath = reports_dir / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Report saved: {filepath}")
    print(f"\n💾 Report saved to: {filepath}")


if __name__ == "__main__":
    main()