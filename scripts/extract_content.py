"""Content extraction script for indexed files."""

import sys
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from src.extractors.manager import ExtractionManager
from src.core.logging import setup_logging

# Setup
setup_logging()
console = Console()


def extract_content():
    """Extract content from documents in database."""
    
    console.print(Panel.fit(
        "📄 Content Extraction\n"
        "Extracting text from PDF, Word, and other documents\n"
        "This will enable full-text search for 'michel' and more!",
        title="Content Extraction Mode",
        border_style="green"
    ))
    
    # Parameters
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    
    # Initialize components
    db = DatabaseManager()
    extractor = ExtractionManager(max_workers=1)
    
    # Get database stats
    db_stats = db.get_statistics()
    console.print(f"📊 Database contains {db_stats['total_files']:,} indexed files")
    
    # Get unprocessed documents
    console.print(f"🔍 Finding documents to extract (limit: {limit})...")
    unprocessed = db.get_unprocessed_documents(limit=limit)
    
    if not unprocessed:
        console.print("[yellow]No unprocessed documents found![/yellow]")
        console.print("All your documents have already been processed, or no documents were found in the database.")
        return
    
    console.print(f"📄 Found {len(unprocessed)} documents to process")
    
    # Show file type breakdown
    type_counts = {}
    for doc in unprocessed:
        ftype = doc['file_type']
        type_counts[ftype] = type_counts.get(ftype, 0) + 1
    
    types_table = Table(title="Documents to Process")
    types_table.add_column("Type", style="cyan")
    types_table.add_column("Count", style="green")
    
    for ftype, count in sorted(type_counts.items()):
        types_table.add_row(ftype.title(), f"{count}")
    
    console.print(types_table)
    console.print()
    
    # Process files
    processed = 0
    successful = 0
    failed = 0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        
        extract_task = progress.add_task("🔍 Extracting content...", total=len(unprocessed))
        
        for doc in unprocessed:
            file_path = Path(doc['path'])
            
            try:
                # Extract content
                result = extractor.extract_single(file_path)
                
                if result.success and result.content.strip():
                    # Update database with extracted content
                    db.update_content(doc['id'], result.content)
                    successful += 1
                    
                    progress.update(
                        extract_task,
                        description=f"✅ Extracted: {file_path.name}"
                    )
                else:
                    failed += 1
                    progress.update(
                        extract_task,
                        description=f"❌ Failed: {file_path.name} - {result.error}"
                    )
                
                processed += 1
                progress.update(extract_task, completed=processed)
                
            except Exception as e:
                failed += 1
                processed += 1
                console.print(f"[red]❌ Error processing {file_path}: {e}[/red]")
                progress.update(extract_task, completed=processed)
    
    # Final results
    console.print("\n" + "="*60)
    
    # Summary table
    summary_table = Table(title="📊 Extraction Summary", show_header=True)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green")
    
    summary_table.add_row("Documents Processed", f"{processed}")
    summary_table.add_row("Successful Extractions", f"{successful}")
    summary_table.add_row("Failed Extractions", f"{failed}")
    
    if processed > 0:
        success_rate = (successful / processed) * 100
        summary_table.add_row("Success Rate", f"{success_rate:.1f}%")
    
    console.print(summary_table)
    
    # Extraction stats
    extract_stats = extractor.get_stats()
    if extract_stats['total_processed'] > 0:
        stats_table = Table(title="⚡ Performance Stats", show_header=True)
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="green")
        
        stats_table.add_row("Average Time", f"{extract_stats['avg_extraction_time']:.2f}s per file")
        stats_table.add_row("Total Time", f"{extract_stats['total_extraction_time']:.1f}s")
        stats_table.add_row("Success Rate", f"{extract_stats['success_rate']:.1f}%")
        
        console.print(stats_table)
    
    # Per-extractor breakdown
    if extract_stats['by_extractor']:
        extractor_table = Table(title="📊 By Extractor Type", show_header=True)
        extractor_table.add_column("Extractor", style="cyan")
        extractor_table.add_column("Processed", style="green")
        extractor_table.add_column("Success Rate", style="yellow")
        extractor_table.add_column("Avg Time", style="blue")
        
        for name, stats in extract_stats['by_extractor'].items():
            if stats['processed'] > 0:
                success_rate = (stats['successful'] / stats['processed']) * 100
                avg_time = stats['total_time'] / stats['processed']
                
                extractor_table.add_row(
                    name,
                    f"{stats['processed']}",
                    f"{success_rate:.1f}%",
                    f"{avg_time:.2f}s"
                )
        
        console.print(extractor_table)
    
    # Next steps
    if successful > 0:
        console.print(Panel.fit(
            f"🎉 Success! Extracted content from {successful} documents\n\n"
            f"🔍 Now you can search for 'michel' in document content!\n"
            f"💡 Run: streamlit run src/ui/app.py\n"
            f"🚀 Try searching for text inside your documents",
            title="Content Extraction Complete",
            border_style="green"
        ))
    else:
        console.print(Panel.fit(
            f"⚠️  No content extracted successfully\n\n"
            f"This might be due to:\n"
            f"• No PDF/Word documents in your index\n" 
            f"• Files are password protected\n"
            f"• Missing python libraries (PyPDF2, python-docx)\n"
            f"💡 Try running: pip install PyPDF2 python-docx openpyxl",
            title="Extraction Complete",
            border_style="yellow"
        ))


def test_single_extraction():
    """Test extraction on a specific file."""
    if len(sys.argv) < 2:
        console.print("[red]Usage: python scripts/extract_content.py <file_path>[/red]")
        return
    
    file_path = Path(sys.argv[1])
    
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return
    
    console.print(f"🔍 Testing extraction on: {file_path}")
    
    extractor = ExtractionManager()
    result = extractor.extract_single(file_path)
    
    if result.success:
        console.print("[green]✅ Extraction successful![/green]")
        console.print(f"📊 Content length: {len(result.content)} characters")
        console.print(f"⏱️  Extraction time: {result.extraction_time:.2f}s")
        
        if result.metadata:
            console.print("📋 Metadata:")
            for key, value in result.metadata.items():
                console.print(f"  {key}: {value}")
        
        # Show first 500 characters
        if result.content:
            preview = result.content[:500]
            console.print("\n📄 Content Preview:")
            console.print(f"[dim]{preview}{'...' if len(result.content) > 500 else ''}[/dim]")
    else:
        console.print(f"[red]❌ Extraction failed: {result.error}[/red]")


if __name__ == "__main__":
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        test_single_extraction()
    else:
        extract_content()