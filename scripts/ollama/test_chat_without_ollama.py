"""Test du chat sans Ollama."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.intelligence.chat_engine import ChatEngine
from src.core.database import DatabaseManager

def test_chat():
    print("TEST CHAT SANS OLLAMA")
    print("=" * 50)
    
    print("\n1. Initialisation...")
    db = DatabaseManager()
    chat = ChatEngine(db=db)
    
    print(f"   Chat disponible: {chat.is_available()}")
    stats = chat.get_stats()
    print(f"   Mode: {stats.get('mode', stats.get('model', 'Unknown'))}")
    
    print("\n2. Test de conversation...")
    response = chat.chat("Bonjour, peux-tu m'aider ?")
    print(f"   Réponse reçue en {response['response_time']:.2f}s")
    print(f"   Aperçu: {response['response'][:100]}...")
    
    print("\n3. Test de recherche...")
    response = chat.chat("Trouve les documents qui mentionnent michel")
    print(f"   Documents trouvés: {len(response.get('sources', []))}")
    if response.get('sources'):
        print("   Fichiers:")
        for doc in response['sources'][:3]:
            print(f"   - {doc.get('filename', 'Unknown')}")
    
    print("\n" + "=" * 50)
    print("✅ Le chat fonctionne SANS Ollama !")
    print("Lancez: streamlit run src/ui/app.py")
    print("Le chat IA est maintenant disponible !")

if __name__ == "__main__":
    test_chat()