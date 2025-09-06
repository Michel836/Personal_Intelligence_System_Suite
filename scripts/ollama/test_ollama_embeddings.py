#!/usr/bin/env python3
"""
Test des embeddings Ollama pour le système 36TB Intelligence
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from intelligence.ollama_embeddings import OllamaEmbeddingGenerator

def test_ollama_embeddings():
    """Test les embeddings Ollama."""
    print("🧠 Test des Embeddings Ollama")
    print("=" * 50)
    
    # Initialiser le générateur
    embedder = OllamaEmbeddingGenerator()
    
    # Statistiques
    stats = embedder.get_stats()
    print("📊 Statut du système:")
    for key, value in stats.items():
        print(f"  - {key}: {value}")
    
    if not embedder.is_available():
        print("❌ Embeddings Ollama non disponibles")
        return
    
    print("\n🧪 Test d'embedding simple...")
    
    # Test de textes
    test_texts = [
        "Ce document traite de contrats immobiliers",
        "Rapport financier avec prêts bancaires", 
        "Intelligence artificielle et recherche sémantique",
        "Michel Dupont conseiller financier"
    ]
    
    print("📝 Textes de test:")
    for i, text in enumerate(test_texts, 1):
        print(f"  {i}. {text}")
    
    # Générer embeddings
    print("\n🔄 Génération des embeddings...")
    embeddings = embedder.generate_batch_embeddings(test_texts, show_progress=True)
    
    # Vérifier résultats
    print(f"\n✅ Résultats: {len([e for e in embeddings if e is not None])}/{len(embeddings)} embeddings générés")
    
    # Test de similarité
    if embeddings[0] is not None and embeddings[1] is not None:
        similarity = embedder.compute_similarity(embeddings[0], embeddings[1])
        print(f"🔍 Similarité entre texte 1 et 2: {similarity:.3f}")
    
    # Test de recherche similaire
    print("\n🎯 Test de recherche de similarité...")
    query = "documents financiers"
    
    text_embeddings = [(test_texts[i], emb) for i, emb in enumerate(embeddings) if emb is not None]
    
    similar = embedder.find_similar_texts(query, text_embeddings, limit=3, min_similarity=0.1)
    
    print(f"Requête: '{query}'")
    print("Résultats similaires:")
    for text, sim in similar:
        print(f"  - {sim:.3f}: {text}")

if __name__ == "__main__":
    test_ollama_embeddings()