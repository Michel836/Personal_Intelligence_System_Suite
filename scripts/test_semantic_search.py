"""Test semantic search capabilities."""

import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.intelligence.semantic_search import SemanticSearchEngine
from src.core.database import DatabaseManager
from src.core.logging import setup_logging

# Setup
setup_logging()
console = Console()


def test_semantic_search():
    """Test semantic search functionality."""
    
    console.print(Panel.fit(
        "🧠 Semantic Search Test\n"
        "Testing AI-powered document understanding",
        title="AI Search Test",
        border_style="blue"
    ))
    
    # Initialize
    db = DatabaseManager()
    semantic_engine = SemanticSearchEngine(db)
    
    # Check availability
    if not semantic_engine.is_available():
        console.print("[red]❌ Semantic search not available![/red]")
        console.print("Install with: pip install sentence-transformers")
        return
    
    console.print("[green]✅ Semantic search engine loaded![/green]")
    
    # Get stats
    stats = semantic_engine.get_stats()
    console.print(f"📄 Documents with content: {stats['documents_with_content']}")
    console.print(f"🧠 Model: {stats['embedding_model']}")
    console.print(f"🎯 Dimensions: {stats['embedding_dimension']}")
    console.print()
    
    if stats['documents_with_content'] == 0:
        console.print("[yellow]⚠️  No documents with extracted content found![/yellow]")
        console.print("Run: python scripts/extract_content.py 100")
        return
    
    # Test queries
    test_queries = [
        "documents about contracts",
        "financial information", 
        "python code files",
        "error messages and logs",
        "installation instructions",
        "michel",  # User's specific search
        "test files and examples"
    ]
    
    console.print("🧠 Testing semantic search queries...")
    console.print()
    
    for i, query in enumerate(test_queries, 1):
        console.print(f"[bold blue]Query {i}: '{query}'[/bold blue]")
        
        try:
            # Semantic search
            results = semantic_engine.semantic_search(
                query, 
                limit=5,
                similarity_threshold=0.2
            )
            
            if results:
                results_table = Table(show_header=True)
                results_table.add_column("File", style="cyan", max_width=40)
                results_table.add_column("Similarity", style="green")
                results_table.add_column("Type", style="yellow")
                
                for result in results:
                    similarity = result.get('semantic_similarity', 0)
                    file_type = result.get('file_type', 'unknown')
                    filename = result.get('filename', 'Unknown')
                    
                    results_table.add_row(
                        filename,
                        f"{similarity:.3f}",
                        file_type
                    )
                
                console.print(results_table)
                
                # Show content preview for best match
                if results[0].get('content_text'):
                    preview = results[0]['content_text'][:200] + "..."
                    console.print(f"[dim]Preview: {preview}[/dim]")
            
            else:
                console.print("[yellow]No results found[/yellow]")
            
            console.print()
            
        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")
            console.print()
    
    # Test hybrid search
    console.print("[bold green]🔄 Testing Hybrid Search[/bold green]")
    
    hybrid_query = sys.argv[1] if len(sys.argv) > 1 else "michel"
    console.print(f"Query: '{hybrid_query}'")
    
    try:
        hybrid_results = semantic_engine.hybrid_search(
            hybrid_query,
            limit=10,
            semantic_weight=0.7,
            text_weight=0.3
        )
        
        if hybrid_results:
            hybrid_table = Table(title="🔄 Hybrid Search Results", show_header=True)
            hybrid_table.add_column("File", style="cyan", max_width=40)
            hybrid_table.add_column("🧠 Semantic", style="green")
            hybrid_table.add_column("📝 Text", style="blue")
            hybrid_table.add_column("🔄 Combined", style="yellow")
            
            for result in hybrid_results:
                semantic_score = result.get('semantic_similarity', 0)
                text_score = result.get('text_relevance', 0)
                combined_score = result.get('combined_score', 0)
                filename = result.get('filename', 'Unknown')
                
                hybrid_table.add_row(
                    filename,
                    f"{semantic_score:.3f}",
                    f"{text_score:.3f}",
                    f"{combined_score:.3f}"
                )
            
            console.print(hybrid_table)
        else:
            console.print("[yellow]No hybrid results found[/yellow]")
    
    except Exception as e:
        console.print(f"[red]❌ Hybrid search error: {e}[/red]")
    
    # Performance summary
    console.print(Panel.fit(
        f"🎉 Semantic search test complete!\n\n"
        f"📊 Model: {stats['embedding_model']}\n"
        f"📄 Documents processed: {stats['documents_with_content']}\n"
        f"🧠 Embeddings cached: {stats['cached_embeddings']}\n\n"
        f"💡 Try the full interface: streamlit run src/ui/app.py\n"
        f"🚀 Then go to '🧠 AI Search' page!",
        title="Test Complete",
        border_style="green"
    ))


if __name__ == "__main__":
    test_semantic_search()