"""Test direct de la connexion Ollama."""

import ollama

print("Test de connexion Ollama")
print("=" * 40)

# Test 1: Connection basique
print("\n1. Test de connexion...")
try:
    response = ollama.list()
    print("   OK - Connection établie!")
    print("   Modèles disponibles:")
    for model in response.get('models', []):
        print(f"   - {model['name']}")
except Exception as e:
    print(f"   ERREUR: {e}")
    print("\n   Solutions:")
    print("   1. Vérifiez qu'Ollama est démarré: ollama serve")
    print("   2. Dans un autre terminal: ollama list")

# Test 2: Test avec DeepSeek si disponible
print("\n2. Test avec un modèle...")
try:
    models = ollama.list()
    model_names = [m['name'] for m in models.get('models', [])]
    
    test_model = None
    for model in ['deepseek-r1', 'deepseek', 'llama3.2:3b', 'llama3.2:1b']:
        if any(model in name for name in model_names):
            test_model = model
            break
    
    if test_model:
        print(f"   Test avec {test_model}...")
        response = ollama.chat(
            model=test_model,
            messages=[{'role': 'user', 'content': 'Dis simplement "OK"'}]
        )
        print(f"   Réponse: {response['message']['content']}")
    else:
        print("   Aucun modèle trouvé. Téléchargez: ollama pull deepseek-r1")
        
except Exception as e:
    print(f"   ERREUR: {e}")

print("\n" + "=" * 40)
print("Si la connexion échoue:")
print("1. Ouvrez PowerShell en admin")
print("2. Tapez: ollama serve")
print("3. Relancez ce test")