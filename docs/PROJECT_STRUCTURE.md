# 📁 Structure du Projet 36TB Intelligence

## 🗂️ Organisation Optimisée

Le projet a été réorganisé pour une meilleure maintenabilité et clarté:

```
Projet_IA_Indexeur_SSD/
│
├── 📄 START.bat                 # Point d'entrée principal (menu interactif)
├── 📄 launcher.py               # Lanceur Python principal
├── 📄 README.md                 # Documentation principale
│
├── 📂 src/                      # Code source principal
│   ├── core/                    # Logique métier centrale
│   ├── scanner/                 # Moteur de scan de fichiers
│   ├── extractors/              # Extracteurs de contenu
│   ├── search/                  # Système de recherche
│   ├── ui/                      # Interfaces utilisateur
│   ├── utils/                   # Utilitaires divers
│   ├── cloud/                   # Synchronisation cloud
│   └── tags/                    # Système de tags
│
├── 📂 scripts/                  # Tous les scripts organisés
│   ├── startup/                 # Scripts de démarrage
│   │   ├── START_SYSTEM.bat
│   │   ├── START_WITHOUT_AI.bat
│   │   └── start_*.bat
│   │
│   ├── ollama/                  # Scripts liés à Ollama/AI
│   │   ├── diagnose_ollama.py
│   │   ├── fix_ollama_admin.bat
│   │   └── validate_ollama.bat
│   │
│   ├── setup/                   # Scripts d'installation
│   │   ├── install_deepseek.bat
│   │   ├── install_gpt_oss.bat
│   │   └── setup_lmstudio.bat
│   │
│   └── diagnostics/             # Scripts de diagnostic
│       ├── check_chat_status.py
│       └── verify_integration.py
│
├── 📂 tests/                    # Tests organisés
│   ├── integration/             # Tests d'intégration
│   │   ├── test_ollama_chat.py
│   │   ├── test_extraction.py
│   │   └── test_analytics.py
│   │
│   └── unit/                    # Tests unitaires
│       └── (à ajouter)
│
├── 📂 docs/                     # Documentation complète
│   ├── guides/                  # Guides d'utilisation
│   │   ├── DISK_SELECTION_FEATURE.md
│   │   ├── ERGONOMIC_IMPROVEMENTS.md
│   │   ├── OLLAMA_TROUBLESHOOT.md
│   │   └── LLM_ALTERNATIVES.md
│   │
│   ├── api/                     # Documentation API
│   └── STATUS.md                # Statut du projet
│
├── 📂 data/                     # Données de l'application
│   ├── indexes/                 # Index de fichiers
│   ├── cache/                   # Cache temporaire
│   ├── reports/                 # Rapports générés
│   └── logs/                    # Journaux
│
└── 📂 .venv/                    # Environnement virtuel Python

```

## 🚀 Utilisation Rapide

### Méthode 1: Menu Interactif (Recommandé)
Double-cliquez sur `START.bat` pour un menu interactif avec toutes les options

### Méthode 2: Lancement Direct
```bash
# Interface principale
python -m streamlit run launcher.py

# Interface moderne
python -m streamlit run src/ui/modern_app.py

# Interface simple
python -m streamlit run src/ui/app.py
```

## 🔧 Scripts Utiles

### Démarrage
- `scripts/startup/` - Tous les scripts de lancement
- `scripts/startup/START_SYSTEM.bat` - Démarrage complet avec AI
- `scripts/startup/START_WITHOUT_AI.bat` - Mode sans AI

### Diagnostics
- `scripts/diagnostics/` - Scripts de vérification
- `scripts/ollama/diagnose_ollama.py` - Diagnostic Ollama

### Installation
- `scripts/setup/` - Scripts d'installation
- `scripts/setup/install_deepseek.bat` - Installation DeepSeek

## 📝 Notes

- Les fichiers essentiels restent à la racine pour un accès rapide
- Tous les scripts sont organisés par catégorie dans `scripts/`
- Les tests sont séparés entre intégration et unitaire
- La documentation est structurée par type (guides, API, etc.)
- Le dossier `data/` contient toutes les données générées

## 🧹 Nettoyage Effectué

✅ Scripts de démarrage organisés dans `scripts/startup/`
✅ Scripts Ollama regroupés dans `scripts/ollama/`
✅ Tests déplacés dans `tests/integration/`
✅ Documentation rangée dans `docs/guides/`
✅ Scripts de diagnostic dans `scripts/diagnostics/`
✅ Point d'entrée unique avec `START.bat`

Cette organisation permet:
- Navigation plus facile
- Maintenance simplifiée
- Séparation claire des responsabilités
- Accès rapide aux fonctions principales