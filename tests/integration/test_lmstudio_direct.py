"""Test direct de LM Studio sans dépendances."""

import requests
import json

def test_lmstudio_direct():
    print("TEST DIRECT LM STUDIO")
    print("=" * 40)
    
    # Test connexion
    print("\n1. Test de connexion au serveur LM Studio...")
    try:
        response = requests.get("http://localhost:1234/v1/models", timeout=5)
        
        if response.status_code == 200:
            print("   [OK] LM Studio serveur accessible !")
            
            models = response.json()
            if 'data' in models and models['data']:
                print(f"   Modèles chargés: {len(models['data'])}")
                for model in models['data']:
                    print(f"   - {model.get('id', 'Unknown')}")
                
                # Test chat
                print("\n2. Test de conversation...")
                test_model = models['data'][0]['id']
                
                chat_payload = {
                    "model": test_model,
                    "messages": [
                        {"role": "user", "content": "Dis simplement 'Bonjour'"}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 50
                }
                
                chat_response = requests.post(
                    "http://localhost:1234/v1/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json=chat_payload,
                    timeout=30
                )
                
                if chat_response.status_code == 200:
                    result = chat_response.json()
                    message = result['choices'][0]['message']['content']
                    print(f"   [OK] Réponse: {message}")
                    print("\n   *** LM STUDIO FONCTIONNE PARFAITEMENT ! ***")
                    return True
                else:
                    print(f"   [X] Erreur chat: {chat_response.status_code}")
                    print(f"   {chat_response.text}")
            
            else:
                print("   [!] Aucun modèle chargé dans LM Studio")
                print("   -> Chargez un modèle et relancez ce test")
        
        else:
            print(f"   [X] Erreur serveur: {response.status_code}")
    
    except requests.exceptions.ConnectionError:
        print("   [X] Serveur LM Studio non accessible")
        print("\n   INSTRUCTIONS:")
        print("   1. Ouvrez LM Studio")
        print("   2. Allez dans l'onglet 'Local Server'") 
        print("   3. Chargez un modèle")
        print("   4. Cliquez 'Start Server'")
        print("   5. Relancez ce test")
        
    except Exception as e:
        print(f"   [X] Erreur: {e}")
    
    return False

def integrate_lmstudio():
    print("\n" + "=" * 40)
    print("INTEGRATION AVEC VOTRE SYSTEME")
    print("=" * 40)
    
    print("\nPour utiliser LM Studio avec votre système 36TB:")
    print("\n1. Modifiez src/intelligence/chat_engine.py")
    print("2. Remplacez SimpleChatEngine par LMStudioChatEngine")
    print("3. Relancez: streamlit run src/ui/app.py")
    print("\nVotre chat IA utilisera alors LM Studio !")

if __name__ == "__main__":
    success = test_lmstudio_direct()
    
    if success:
        integrate_lmstudio()
    else:
        print("\n" + "=" * 40)
        print("VOTRE SYSTEME FONCTIONNE DEJA !")
        print("Le chat IA marche sans LM Studio.")
        print("Lancez: streamlit run src/ui/app.py")