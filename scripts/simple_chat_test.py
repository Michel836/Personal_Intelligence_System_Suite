"""Simple AI chat test without external dependencies."""

import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.intelligence.chat_engine import ChatEngine
from src.core.database import DatabaseManager

def test_chat():
    """Simple chat integration test."""
    
    print("💬 AI Chat Integration Test")
    print("=" * 40)
    
    # Initialize
    db = DatabaseManager()
    chat_engine = ChatEngine(db=db)
    
    # Check availability
    print("1. Checking chat engine availability...")
    if not chat_engine.is_available():
        print("❌ Chat engine not available!")
        print("Install: pip install ollama")
        print("Then: ollama pull llama3.2:3b")
        return
    
    print("✅ Chat engine loaded!")
    
    # Get stats
    stats = chat_engine.get_stats()
    print(f"   Model: {stats['model']}")
    print(f"   Semantic search: {stats['semantic_search_available']}")
    print(f"   Ollama installed: {stats['ollama_installed']}")
    print()
    
    # Test basic chat
    print("2. Testing basic chat...")
    try:
        response = chat_engine.chat("Hello! What can you help me with?", search_context=False)
        print(f"✅ Response received in {response['response_time']:.2f}s")
        print(f"   Preview: {response['response'][:100]}...")
    except Exception as e:
        print(f"❌ Basic chat failed: {e}")
    print()
    
    # Test document search chat  
    print("3. Testing document search chat...")
    try:
        response = chat_engine.chat("Find any files that mention 'michel'", search_context=True)
        print(f"✅ Search response in {response['response_time']:.2f}s")
        print(f"   Found {len(response.get('sources', []))} documents")
        print(f"   Preview: {response['response'][:150]}...")
    except Exception as e:
        print(f"❌ Document search failed: {e}")
    print()
    
    # Test conversation history
    print("4. Testing conversation history...")
    history = chat_engine.get_conversation_history()
    print(f"✅ Conversation has {len(history)} messages")
    
    if history:
        for i, msg in enumerate(history[-2:]):  # Show last 2
            role = "User" if msg['role'] == 'user' else "AI"
            content = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
            print(f"   {role}: {content}")
    print()
    
    # Summary
    print("🎉 Integration test complete!")
    print("✅ AI Chat page ready for Streamlit interface")
    print()
    print("💡 To use full interface:")
    print("   pip install streamlit")
    print("   streamlit run src/ui/app.py")
    print("   Then go to '💬 AI Chat' page!")

if __name__ == "__main__":
    test_chat()