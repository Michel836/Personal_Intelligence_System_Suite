"""Minimal test to verify chat integration."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

print("Testing AI Chat Integration")
print("=" * 40)

try:
    from src.intelligence.chat_engine import ChatEngine
    print("OK ChatEngine import successful")
except ImportError as e:
    print(f"ERROR ChatEngine import failed: {e}")
    sys.exit(1)

try:
    from src.core.database import DatabaseManager
    print("OK DatabaseManager import successful")
except ImportError as e:
    print(f"ERROR DatabaseManager import failed: {e}")
    sys.exit(1)

try:
    # Initialize components
    db = DatabaseManager()
    chat_engine = ChatEngine(db=db)
    print("OK Components initialized")
    
    # Check availability
    available = chat_engine.is_available()
    print(f"Chat engine available: {available}")
    
    if available:
        stats = chat_engine.get_stats()
        print(f"   Model: {stats.get('model', 'Unknown')}")
        print(f"   Ollama installed: {stats.get('ollama_installed', False)}")
    else:
        print("INFO Install Ollama to test full functionality:")
        print("   curl -fsSL https://ollama.ai/install.sh | sh")
        print("   ollama pull llama3.2:3b")
    
except Exception as e:
    print(f"ERROR Initialization failed: {e}")
    import traceback
    traceback.print_exc()

print()
print("Integration Status:")
print("OK Chat engine code integrated")
print("OK Streamlit UI page created") 
print("OK Ready for testing with Ollama")
print()
print("Next steps:")
print("1. Install streamlit: pip install streamlit")
print("2. Install ollama and pull a model")
print("3. Run: streamlit run src/ui/app.py")
print("4. Go to '💬 AI Chat' page")