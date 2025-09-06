# 🤖 Installation d'Ollama sur Windows

Ce guide vous explique comment installer Ollama pour activer le chat IA conversationnel.

## 📥 Étape 1 : Télécharger Ollama

1. Visitez https://ollama.ai/download
2. Cliquez sur "Download for Windows" 
3. Téléchargez le fichier `.exe` (environ 200 MB)
4. Exécutez l'installateur en tant qu'administrateur

## ⚙️ Étape 2 : Vérifier l'installation

Ouvrez PowerShell ou l'invite de commande et tapez :
```powershell
ollama --version
```

Vous devriez voir quelque chose comme :
```
ollama version is 0.x.x
```

## 🧠 Étape 3 : Télécharger un modèle IA

Téléchargez un modèle de langage (recommandé : llama3.2:3b) :

```powershell
ollama pull llama3.2:3b
```

**Options de modèles :**
- `llama3.2:1b` - Plus rapide, moins précis (1.3 GB)
- `llama3.2:3b` - Équilibré, recommandé (2.0 GB) 
- `llama3.1:8b` - Plus précis, plus lent (4.7 GB)

## 🐍 Étape 4 : Installer le package Python

```powershell
pip install ollama
```

## ✅ Étape 5 : Tester l'installation

Utilisez notre script de vérification :
```powershell
cd "C:\Users\chume\Desktop\Projet_IA_Indexeur SSD"
python scripts/check_ollama.py
```

## 🚀 Étape 6 : Lancer l'interface

```powershell
pip install streamlit
streamlit run src/ui/app.py
```

Allez ensuite à la page "💬 AI Chat" !

## 🛠️ Dépannage

### Problème : "ollama command not found"
- Redémarrez votre terminal après installation
- Vérifiez que Ollama est dans votre PATH
- Réinstallez Ollama en tant qu'administrateur

### Problème : "Connection error"
- Assurez-vous que le service Ollama fonctionne
- Redémarrez Windows si nécessaire
- Vérifiez le pare-feu Windows

### Problème : "No models available"
- Téléchargez un modèle : `ollama pull llama3.2:3b`
- Vérifiez l'espace disque (minimum 4 GB libres)

### Problème : Modèle trop lent
- Utilisez un modèle plus petit : `ollama pull llama3.2:1b`
- Fermez d'autres applications pour libérer RAM

## 📊 Configuration recommandée

**Minimum :**
- RAM : 8 GB
- Espace disque : 4 GB libre
- Processeur : Intel/AMD moderne

**Optimal :**
- RAM : 16 GB+
- SSD : Pour un accès rapide
- GPU : Support CUDA/ROCm (optionnel)

## 🎯 Une fois configuré

Vous pourrez :
- ✅ Converser avec vos documents en langage naturel
- ✅ Poser des questions sur des fichiers spécifiques  
- ✅ Obtenir des résumés intelligents de votre collection
- ✅ Chercher avec recherche sémantique contextuelle
- ✅ Maintenir des conversations avec historique

**Exemple de questions :**
- "Trouve-moi tous les documents qui mentionnent 'michel'"
- "Résume mes contrats importants"
- "Qu'est-ce que ce fichier PDF contient ?"
- "Montre-moi les documents financiers de 2023"