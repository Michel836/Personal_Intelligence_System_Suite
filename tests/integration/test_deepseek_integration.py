"""Test de l'intégration DeepSeek-R1 avec le système."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

def test_deepseek():
    print("=" * 50)
    print("   TEST INTEGRATION DEEPSEEK-R1")
    print("=" * 50)
    
    # Test Ollama
    print("\n[1/3] Vérification d'Ollama...")
    import subprocess
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=10)
        if 'deepseek-r1' in result.stdout or 'deepseek' in result.stdout:
            print("    ✓ DeepSeek-R1 installé")
        else:
            print("    ⚠ DeepSeek non trouvé")
            print("    Lancez: ollama pull deepseek-r1")
    except Exception as e:
        print(f"    ✗ Erreur: {e}")
    
    # Test ChatEngine
    print("\n[2/3] Test du ChatEngine...")
    try:
        from src.intelligence.chat_engine import ChatEngine
        from src.core.database import DatabaseManager
        
        db = DatabaseManager()
        chat = ChatEngine(db=db)
        
        if chat.is_available():
            print("    ✓ ChatEngine disponible")
            print(f"    Modèle: {chat.model_name}")
            
            # Test simple
            print("\n[3/3] Test de conversation...")
            response = chat.chat("Bonjour, es-tu prêt à m'aider?", search_context=False)
            if 'response' in response:
                print("    ✓ Réponse reçue")
                print(f"    Aperçu: {response['response'][:100]}...")
            else:
                print(f"    ⚠ Erreur: {response.get('error', 'Inconnu')}")
        else:
            print("    ✗ ChatEngine non disponible")
            print("    Vérifiez qu'Ollama est démarré")
            
    except Exception as e:
        print(f"    ✗ Erreur: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 50)
    print("         PROCHAINES ETAPES")
    print("=" * 50)
    print("1. Si tout est ✓ : streamlit run src/ui/app.py")
    print("2. Allez à la page '💬 AI Chat'")
    print("3. Conversez avec vos 36TB de documents !")
    print("\nDeepSeek-R1 est prêt à analyser vos données !")

if __name__ == "__main__":
    test_deepseek()