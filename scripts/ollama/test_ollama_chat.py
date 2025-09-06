#!/usr/bin/env python3
"""
Script de test pour l'intégration Ollama dans le système de chat
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from intelligence.chat_engine import ChatEngine

def test_ollama_integration():
    """Test l'intégration Ollama."""
    print("🚀 Test d'intégration Ollama")
    print("=" * 50)
    
    # Initialiser le moteur de chat
    chat = ChatEngine()
    
    # Afficher les statistiques
    stats = chat.get_stats()
    print("📊 Statut du système:")
    for key, value in stats.items():
        print(f"  - {key}: {value}")
    
    print("\n" + "=" * 50)
    print("🗣️  Test de conversation...")
    
    # Test de conversation
    questions = [
        "Bonjour! Peux-tu te présenter?",
        "Que peux-tu faire pour m'aider avec mes documents?",
        "Comment puis-je utiliser la recherche sémantique?"
    ]
    
    for i, question in enumerate(questions, 1):
        print(f"\n[Q{i}] {question}")
        try:
            response = chat.chat(question, search_context=False)
            print(f"[R{i}] {response.get('response', 'Pas de réponse')}")
            print(f"    └── Modèle: {response.get('model', 'Unknown')}")
            print(f"    └── Temps: {response.get('response_time', 0):.2f}s")
        except Exception as e:
            print(f"[ERROR] {e}")
    
    print("\n" + "=" * 50)
    print("✅ Test terminé!")

if __name__ == "__main__":
    test_ollama_integration()