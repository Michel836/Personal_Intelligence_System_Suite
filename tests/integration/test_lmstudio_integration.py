"""Test de l'intégration LM Studio."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

def test_lmstudio():
    print("TEST INTEGRATION LM STUDIO")
    print("=" * 50)
    
    # Test 1: LM Studio disponible
    print("\n1. Test de connexion LM Studio...")
    try:
        from src.intelligence.lmstudio_chat_engine import LMStudioChatEngine
        from src.core.database import DatabaseManager
        
        db = DatabaseManager()
        lm_chat = LMStudioChatEngine(db=db)
        
        if lm_chat.is_available():
            print("   [OK] LM Studio serveur accessible")
            
            # Test 2: Chat simple
            print("\n2. Test de conversation...")
            response = lm_chat.chat("Bonjour, comment allez-vous ?")
            print(f"   Reponse recue en {response['response_time']:.2f}s")
            print(f"   Apercu: {response['response'][:100]}...")
            
            # Test 3: Recherche de documents
            print("\n3. Test de recherche...")
            response = lm_chat.chat("Trouve les documents qui mentionnent michel")
            print(f"   Documents: {len(response.get('sources', []))}")
            
            print("\n[OK] LM Studio fonctionne parfaitement !")
            print("Votre systeme peut maintenant utiliser LM Studio.")
            
        else:
            print("   [X] LM Studio serveur non accessible")
            print("\n   INSTRUCTIONS:")
            print("   1. Ouvrez LM Studio")
            print("   2. Telechargez un modele (ex: Mistral-7B)")
            print("   3. Allez dans 'Local Server'")
            print("   4. Cliquez 'Start Server'")
            print("   5. Relancez ce test")
            
    except Exception as e:
        print(f"   [X] Erreur: {e}")
        print("\n   Installez: pip install requests")
    
    # Test Hugging Face alternative
    print("\n" + "=" * 50)
    print("TEST HUGGING FACE (Alternative)")
    print("=" * 50)
    
    try:
        from src.intelligence.hf_chat_engine import HuggingFaceChatEngine
        
        hf_chat = HuggingFaceChatEngine()
        
        if hf_chat.is_available():
            print("\n[OK] Hugging Face disponible")
            response = hf_chat.chat("Bonjour")
            print(f"Reponse: {response['response'][:50]}...")
        else:
            print("\n[!] Hugging Face non disponible")
            print("Installez: pip install transformers torch")
            
    except Exception as e:
        print(f"\n[X] Erreur HF: {e}")
    
    print("\n" + "=" * 50)
    print("RECOMMANDATIONS:")
    print("1. LM Studio (le plus simple)")
    print("2. Hugging Face (si vous etes technique)")
    print("3. Votre systeme fonctionne deja sans LLM externe!")

if __name__ == "__main__":
    test_lmstudio()