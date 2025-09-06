#!/usr/bin/env python3
"""
Test d'extraction de contenu pour le système 36TB Intelligence
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from extractors.manager import ExtractionManager
from core.database import DatabaseManager

def test_extraction():
    """Test l'extraction de contenu."""
    print("🧪 Test d'extraction de contenu")
    print("=" * 50)
    
    # Initialiser les composants
    extraction_manager = ExtractionManager()
    db = DatabaseManager()
    
    print("📊 Extensions supportées:")
    extensions = extraction_manager.get_supported_extensions()
    for ext in sorted(extensions):
        print(f"  - {ext}")
    
    print("\n🗂️ Test sur document exemple...")
    test_file = Path("test_documents/test.txt")
    
    if test_file.exists():
        # Test d'extraction
        result = extraction_manager.extract_single(test_file)
        
        print(f"📄 Fichier: {test_file}")
        print(f"✅ Succès: {result.success}")
        
        if result.success:
            print(f"📝 Contenu extrait: {result.content[:200]}...")
            print(f"🔤 Nombre de caractères: {len(result.content) if result.content else 0}")
            print(f"⏱️ Temps d'extraction: {result.extraction_time:.3f}s")
            
            if result.metadata:
                print("🏷️ Métadonnées:")
                for key, value in result.metadata.items():
                    print(f"  - {key}: {value}")
        else:
            print(f"❌ Erreur: {result.error}")
    else:
        print(f"❌ Fichier test non trouvé: {test_file}")
    
    # Statistiques
    print("\n📈 Statistiques d'extraction:")
    stats = extraction_manager.get_stats()
    for key, value in stats.items():
        if key != 'by_extractor':
            print(f"  - {key}: {value}")

if __name__ == "__main__":
    test_extraction()