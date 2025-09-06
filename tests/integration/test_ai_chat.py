"""Test rapide de l'intégration AI Chat."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

def test_ai_integration():
    """Test complet de l'intégration AI."""
    
    print("=" * 50)
    print("    TEST INTEGRATION AI CHAT COMPLET")
    print("=" * 50)
    
    # Test 1: Imports
    print("\n[1/4] Test des imports...")
    try:
        from src.intelligence.chat_engine import ChatEngine
        from src.core.database import DatabaseManager
        print("    ✓ Imports OK")
    except Exception as e:
        print(f"    ✗ Erreur imports: {e}")
        return False
    
    # Test 2: Initialisation
    print("\n[2/4] Test d'initialisation...")
    try:
        db = DatabaseManager()
        chat_engine = ChatEngine(db=db)
        print("    ✓ Initialisation OK")
    except Exception as e:
        print(f"    ✗ Erreur init: {e}")
        return False
    
    # Test 3: Disponibilité Ollama
    print("\n[3/4] Test disponibilité Ollama...")
    try:
        available = chat_engine.is_available()
        if available:
            print("    ✓ Ollama disponible !")
            stats = chat_engine.get_stats()
            print(f"    Modèle: {stats.get('model', 'Inconnu')}")
        else:
            print("    ⚠ Ollama non disponible")
            print("    Lancez: validate_ollama.bat")
    except Exception as e:
        print(f"    ✗ Erreur test Ollama: {e}")
    
    # Test 4: Interface Streamlit
    print("\n[4/4] Test interface Streamlit...")
    try:
        with open("src/ui/app.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        if "def ai_chat_page" in content and "ChatEngine" in content:
            print("    ✓ Interface AI Chat intégrée")
        else:
            print("    ✗ Interface AI Chat manquante")
            
    except Exception as e:
        print(f"    ✗ Erreur interface: {e}")
    
    print("\n" + "=" * 50)
    print("             PROCHAINES ÉTAPES")
    print("=" * 50)
    print("1. Lancez: validate_ollama.bat")
    print("2. Puis: pip install streamlit (si pas fait)")
    print("3. Enfin: streamlit run src/ui/app.py")
    print("4. Allez à la page '💬 AI Chat'")
    print("\nVotre système de chat IA sera opérationnel !")

if __name__ == "__main__":
    test_ai_integration()