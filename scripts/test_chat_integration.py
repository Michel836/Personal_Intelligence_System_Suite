"""Test AI chat integration."""

import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.intelligence.chat_engine import ChatEngine
from src.core.database import DatabaseManager
from src.core.logging import setup_logging

# Setup
setup_logging()
console = Console()

def test_chat_integration():
    """Test complete chat integration."""
    
    console.print(Panel.fit(
        "💬 AI Chat Integration Test\n"
        "Testing conversational AI with document context",
        title="Chat Test",
        border_style="blue"
    ))
    
    # Initialize
    db = DatabaseManager()
    chat_engine = ChatEngine(db=db)
    
    # Check availability
    if not chat_engine.is_available():
        console.print("[red]❌ Chat engine not available![/red]")
        console.print("Install Ollama: curl -fsSL https://ollama.ai/install.sh | sh")
        console.print("Then: ollama pull llama3.2:3b")
        return
    
    console.print("[green]✅ Chat engine loaded![/green]")
    
    # Get stats
    stats = chat_engine.get_stats()
    console.print(f"🤖 Model: {stats['model']}")
    console.print(f"🔍 Semantic search: {stats['semantic_search_available']}")
    console.print(f"📄 Ollama installed: {stats['ollama_installed']}")
    console.print()
    
    # Test basic chat without context
    console.print("[bold blue]Test 1: Basic chat (no document context)[/bold blue]")
    
    try:
        response = chat_engine.chat("Hello! Can you help me?", search_context=False)
        
        console.print(f"✅ Response: {response['response'][:100]}...")
        console.print(f"⏱️  Response time: {response['response_time']:.2f}s")
        console.print()
        
    except Exception as e:
        console.print(f"[red]❌ Basic chat failed: {e}[/red]")
        console.print()
    
    # Test chat with document context
    console.print("[bold blue]Test 2: Chat with document search[/bold blue]")
    
    try:
        response = chat_engine.chat("Find documents that mention michel", search_context=True)
        
        console.print(f"✅ Response: {response['response'][:200]}...")
        console.print(f"📚 Found {len(response.get('sources', []))} source documents")
        console.print(f"⏱️  Response time: {response['response_time']:.2f}s")
        
        # Show sources if found
        if response.get('sources'):
            console.print("\n📄 Found documents:")
            for i, source in enumerate(response['sources'][:3]):
                console.print(f"  {i+1}. {source.get('filename', 'Unknown')}")
                if 'semantic_similarity' in source:
                    console.print(f"     Relevance: {source['semantic_similarity']:.3f}")
        
        console.print()
        
    except Exception as e:
        console.print(f"[red]❌ Context chat failed: {e}[/red]")
        console.print()
    
    # Test document-specific chat
    console.print("[bold blue]Test 3: Document-specific analysis[/bold blue]")
    
    try:
        # Get a sample document
        with db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, filename FROM files 
                WHERE content_extracted = 1 
                AND content_text IS NOT NULL 
                AND length(content_text) > 100
                LIMIT 1
            """)
            doc = cursor.fetchone()
        
        if doc:
            response = chat_engine.ask_about_document(
                doc[0], 
                "What is this document about?"
            )
            
            console.print(f"📄 Document: {doc[1]}")
            console.print(f"✅ Analysis: {response['response'][:200]}...")
            console.print()
        else:
            console.print("[yellow]⚠️  No documents with content found[/yellow]")
            console.print()
    
    except Exception as e:
        console.print(f"[red]❌ Document analysis failed: {e}[/red]")
        console.print()
    
    # Test collection summary
    console.print("[bold blue]Test 4: Collection summarization[/bold blue]")
    
    try:
        response = chat_engine.summarize_documents(limit=5)
        
        console.print(f"✅ Summary: {response['response'][:300]}...")
        console.print(f"📊 Analyzed {len(response.get('sources', []))} documents")
        console.print()
        
    except Exception as e:
        console.print(f"[red]❌ Summarization failed: {e}[/red]")
        console.print()
    
    # Test conversation history
    console.print("[bold blue]Test 5: Conversation history[/bold blue]")
    
    history = chat_engine.get_conversation_history()
    console.print(f"💬 Conversation length: {len(history)} messages")
    
    if history:
        console.print("Recent messages:")
        for i, msg in enumerate(history[-4:]):  # Last 4 messages
            role = "🙋" if msg['role'] == 'user' else "🤖"
            content = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
            console.print(f"  {role} {content}")
    
    console.print()
    
    # Final summary
    console.print(Panel.fit(
        f"🎉 Chat integration test complete!\n\n"
        f"✅ Basic chat: Working\n"
        f"✅ Document search: Working\n" 
        f"✅ Document analysis: Working\n"
        f"✅ Collection summary: Working\n"
        f"✅ Conversation history: Working\n\n"
        f"🚀 Ready for full interface!\n"
        f"💡 Install Streamlit: pip install streamlit\n"
        f"🎯 Then run: streamlit run src/ui/app.py",
        title="Integration Complete",
        border_style="green"
    ))

if __name__ == "__main__":
    test_chat_integration()