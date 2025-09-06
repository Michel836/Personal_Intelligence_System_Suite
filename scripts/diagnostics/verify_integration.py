"""Verify AI chat integration files and structure."""

from pathlib import Path

def verify_integration():
    """Verify that all integration files are in place."""
    
    print("Verifying AI Chat Integration")
    print("=" * 40)
    
    base_path = Path(__file__).parent
    
    # Check core files
    files_to_check = [
        "src/intelligence/__init__.py",
        "src/intelligence/chat_engine.py",
        "src/intelligence/embeddings.py", 
        "src/intelligence/semantic_search.py",
        "src/ui/app.py",
        "src/core/database.py"
    ]
    
    print("1. Checking core integration files...")
    all_present = True
    for file_path in files_to_check:
        full_path = base_path / file_path
        if full_path.exists():
            print(f"   OK {file_path}")
        else:
            print(f"   ERROR Missing: {file_path}")
            all_present = False
    
    print()
    
    # Check if ChatEngine is properly defined
    print("2. Checking ChatEngine implementation...")
    try:
        chat_engine_path = base_path / "src/intelligence/chat_engine.py"
        with open(chat_engine_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        required_methods = [
            "class ChatEngine:",
            "def __init__",
            "def chat(",
            "def ask_about_document(",
            "def summarize_documents(",
            "def is_available(",
            "def get_stats("
        ]
        
        for method in required_methods:
            if method in content:
                print(f"   OK {method}")
            else:
                print(f"   ERROR Missing: {method}")
                all_present = False
        
    except Exception as e:
        print(f"   ERROR Reading chat_engine.py: {e}")
        all_present = False
    
    print()
    
    # Check if UI integration is complete
    print("3. Checking UI integration...")
    try:
        ui_path = base_path / "src/ui/app.py"
        with open(ui_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        ui_requirements = [
            "from src.intelligence.chat_engine import ChatEngine",
            "st.session_state.chat_engine = ChatEngine()",
            "def ai_chat_page():",
            '"💬 AI Chat"'
        ]
        
        for requirement in ui_requirements:
            if requirement in content:
                print(f"   OK {requirement}")
            else:
                print(f"   ERROR Missing: {requirement}")
                all_present = False
        
    except Exception as e:
        print(f"   ERROR Reading app.py: {e}")
        all_present = False
    
    print()
    
    # Final status
    if all_present:
        print("Integration Status: COMPLETE")
        print("OK All files and components integrated successfully")
        print()
        print("Next steps:")
        print("1. Install dependencies:")
        print("   pip install streamlit loguru ollama sentence-transformers")
        print("2. Install Ollama:")
        print("   curl -fsSL https://ollama.ai/install.sh | sh")
        print("3. Download AI model:")
        print("   ollama pull llama3.2:3b")
        print("4. Launch interface:")
        print("   streamlit run src/ui/app.py")
        print("5. Go to 'AI Chat' page and start conversations!")
    else:
        print("Integration Status: INCOMPLETE")
        print("ERROR Some components are missing or incomplete")

if __name__ == "__main__":
    verify_integration()