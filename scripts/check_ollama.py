"""Check Ollama installation and setup."""

import subprocess
import sys
from pathlib import Path

def check_ollama_installation():
    """Check if Ollama is properly installed and configured."""
    
    print("Checking Ollama Installation")
    print("=" * 40)
    
    # Check if ollama command exists
    print("1. Checking Ollama command...")
    try:
        result = subprocess.run(['ollama', '--version'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"   OK Ollama installed: {result.stdout.strip()}")
        else:
            print("   ERROR Ollama command failed")
            print("   Install from: https://ollama.ai/download")
            return False
    except FileNotFoundError:
        print("   ERROR Ollama not found in PATH")
        print("   Install from: https://ollama.ai/download")
        return False
    except Exception as e:
        print(f"   ERROR Checking Ollama: {e}")
        return False
    
    # Check available models
    print("\n2. Checking available models...")
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            models = result.stdout.strip()
            if models and "llama" in models.lower():
                print("   OK Models found:")
                print(f"   {models}")
            else:
                print("   WARNING No models found")
                print("   Run: ollama pull llama3.2:3b")
                print("   Or: ollama pull llama3.1:8b")
        else:
            print(f"   ERROR Getting models: {result.stderr}")
    except Exception as e:
        print(f"   ERROR Checking models: {e}")
    
    # Check Python ollama package
    print("\n3. Checking Python ollama package...")
    try:
        import ollama
        print("   OK ollama package installed")
        
        # Try to connect
        try:
            models = ollama.list()
            print(f"   OK Connection successful: {len(models.get('models', []))} models")
        except Exception as e:
            print(f"   WARNING Connection issue: {e}")
            print("   Make sure Ollama service is running")
    
    except ImportError:
        print("   ERROR ollama package not installed")
        print("   Run: pip install ollama")
        return False
    
    # Test chat functionality
    print("\n4. Testing chat functionality...")
    try:
        # Add src to path for testing
        sys.path.append(str(Path(__file__).parent.parent))
        from src.intelligence.chat_engine import ChatEngine
        
        chat_engine = ChatEngine()
        available = chat_engine.is_available()
        
        if available:
            print("   OK Chat engine ready!")
            stats = chat_engine.get_stats()
            print(f"   Model: {stats.get('model', 'Unknown')}")
        else:
            print("   ERROR Chat engine not available")
            print("   Check Ollama installation and models")
    
    except Exception as e:
        print(f"   ERROR Testing chat: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 40)
    print("Setup Complete!")
    print("Launch interface: streamlit run src/ui/app.py")
    print("Go to: 'AI Chat' page")
    
    return True

if __name__ == "__main__":
    check_ollama_installation()