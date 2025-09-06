"""Full indexing script with database storage."""

import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel
from rich.live import Live

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.scanner.fast_engine import FastScannerEngine
from src.core.database import DatabaseManager
from src.core.logging import setup_logging
from src.scanner.models import FileInfo

# Setup
setup_logging()
console = Console()


def full_index_scan():
    """Run full indexing scan with database storage."""
    
    console.print(Panel.fit(
        "🔍 36TB Intelligence - Full Indexing Scan\n"
        "Scanning, analyzing and storing your digital life",
        title="Full Index Mode",
        border_style="blue"
    ))
    
    # Parameters
    drive = sys.argv[1] if len(sys.argv) > 1 else "C:"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 0 = unlimited
    
    scan_path = Path(drive + "\\") if not drive.endswith("\\") else Path(drive)
    
    if not scan_path.exists():
        console.print(f"[red]❌ Drive {drive} not found![/red]")
        return
    
    # Initialize components
    scanner = FastScannerEngine()
    db = DatabaseManager()
    
    console.print(f"📁 [bold]Scan Path:[/bold] {scan_path}")
    console.print(f"🎯 [bold]Limit:[/bold] {'Unlimited' if limit == 0 else f'{limit:,} files'}")
    console.print(f"💾 [bold]Database:[/bold] {db.db_path}")
    console.print()
    
    # Improved batch processing setup with memory management
    batch_size = min(500, 1000)  # Smaller batches for better memory control
    current_batch: List[FileInfo] = []
    total_processed = 0
    total_saved = 0
    start_time = time.time()
    max_memory_items = 2000  # Maximum items to keep in memory at once
    
    # Progress tracking
    stats = {
        'files_scanned': 0,
        'files_saved': 0,
        'total_size': 0,
        'by_type': {},
        'by_priority': {},
        'errors': 0
    }
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        
        # Create progress tasks
        if limit > 0:
            scan_task = progress.add_task("🔍 Scanning files...", total=limit)
        else:
            scan_task = progress.add_task("🔍 Scanning files...", total=None)
        
        save_task = progress.add_task("💾 Saving batches...", total=None)
        
        try:
            # Main scanning loop
            for file_info in scanner.fast_scan(scan_path, limit=limit if limit > 0 else None):
                current_batch.append(file_info)
                total_processed += 1
                
                # Update statistics
                stats['files_scanned'] += 1
                stats['total_size'] += file_info.size_bytes
                
                # Count by type
                ftype = file_info.file_type.value
                stats['by_type'][ftype] = stats['by_type'].get(ftype, 0) + 1
                
                # Count by priority
                priority = file_info.priority.value
                stats['by_priority'][priority] = stats['by_priority'].get(priority, 0) + 1
                
                # Update progress
                if limit > 0:
                    progress.update(scan_task, completed=total_processed)
                else:
                    progress.update(
                        scan_task, 
                        description=f"🔍 Scanning... {total_processed:,} files"
                    )
                
                # Save batch when full or memory limit reached
                if len(current_batch) >= batch_size or total_processed % max_memory_items == 0:
                    try:
                        if current_batch:  # Only save if we have items
                            saved = db.save_files_batch(current_batch)
                            total_saved += saved
                            current_batch.clear()  # Free memory immediately
                            
                            progress.update(
                                save_task,
                                description=f"💾 Saved: {total_saved:,} files"
                            )
                        
                    except Exception as e:
                        console.print(f"[red]❌ Error saving batch: {e}[/red]")
                        stats['errors'] += 1
                        current_batch.clear()  # Clear even on error to prevent memory issues
            
            # Save remaining files
            if current_batch:
                try:
                    saved = db.save_files_batch(current_batch)
                    total_saved += saved
                    progress.update(
                        save_task,
                        description=f"💾 Final save: {total_saved:,} files"
                    )
                except Exception as e:
                    console.print(f"[red]❌ Error saving final batch: {e}[/red]")
                    stats['errors'] += 1
        
        except KeyboardInterrupt:
            console.print("\n[yellow]⏹️  Scan interrupted by user[/yellow]")
        except Exception as e:
            console.print(f"[red]❌ Scan error: {e}[/red]")
            stats['errors'] += 1
    
    # Final results
    total_time = time.time() - start_time
    console.print("\n" + "="*60)
    
    # Summary table
    summary_table = Table(title="📊 Indexing Summary", show_header=True)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green")
    
    summary_table.add_row("Files Scanned", f"{stats['files_scanned']:,}")
    summary_table.add_row("Files Saved", f"{total_saved:,}")
    summary_table.add_row("Total Size", f"{stats['total_size'] / (1024**3):.2f} GB")
    summary_table.add_row("Duration", f"{total_time:.1f} seconds")
    summary_table.add_row("Scan Speed", f"{stats['files_scanned'] / total_time:.0f} files/sec")
    summary_table.add_row("Save Rate", f"{total_saved / total_time:.0f} files/sec")
    if stats['errors'] > 0:
        summary_table.add_row("Errors", f"{stats['errors']}", style="red")
    
    console.print(summary_table)
    
    # File types breakdown
    if stats['by_type']:
        types_table = Table(title="📄 File Types", show_header=True)
        types_table.add_column("Type", style="cyan")
        types_table.add_column("Count", style="green")
        types_table.add_column("Percentage", style="yellow")
        
        sorted_types = sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True)
        for ftype, count in sorted_types:
            percentage = (count / stats['files_scanned']) * 100
            types_table.add_row(ftype.title(), f"{count:,}", f"{percentage:.1f}%")
        
        console.print(types_table)
    
    # Priority breakdown
    if stats['by_priority']:
        priority_table = Table(title="🎯 Priorities", show_header=True)
        priority_table.add_column("Priority", style="cyan")
        priority_table.add_column("Count", style="green")
        priority_table.add_column("Percentage", style="yellow")
        
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        sorted_priorities = sorted(
            stats['by_priority'].items(), 
            key=lambda x: priority_order.get(x[0], 999)
        )
        
        for priority, count in sorted_priorities:
            percentage = (count / stats['files_scanned']) * 100
            priority_table.add_row(priority.title(), f"{count:,}", f"{percentage:.1f}%")
        
        console.print(priority_table)
    
    # Save scan statistics to database
    if total_saved > 0:
        try:
            db.save_scan_stats({
                'scan_path': str(scan_path),
                'total_files': stats['files_scanned'],
                'total_bytes': stats['total_size'],
                'scan_duration': total_time,
                'files_per_second': stats['files_scanned'] / total_time,
                'started_at': datetime.fromtimestamp(start_time).isoformat(),
                'completed_at': datetime.now().isoformat(),
                'metadata': {
                    'by_type': stats['by_type'],
                    'by_priority': stats['by_priority'],
                    'files_saved': total_saved,
                    'errors': stats['errors']
                }
            })
            console.print(f"\n✅ [green]Scan statistics saved to database[/green]")
        except Exception as e:
            console.print(f"\n❌ [red]Error saving scan stats: {e}[/red]")
    
    # Database statistics
    db_stats = db.get_statistics()
    console.print(f"\n💾 [bold]Database now contains {db_stats['total_files']:,} files ({db_stats['total_gb']:.2f} GB)[/bold]")
    
    console.print(Panel.fit(
        f"✅ Indexing complete!\n\n"
        f"🔍 Run: streamlit run src/ui/app.py\n"
        f"💡 Then search through your {total_saved:,} indexed files!",
        title="Next Steps",
        border_style="green"
    ))


if __name__ == "__main__":
    full_index_scan()