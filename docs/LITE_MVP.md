# PISS Lite — MVP local

Lite sert à retrouver les fichiers et leur contenu sur une machine personnelle.
Le même point d’entrée canonique `src/ui/app.py` propose désormais quatre écrans :
Scanner, Extraire, Search et État du système. SMART et FULL gardent leur interface.

## Installer et lancer sous Linux / Kubuntu

Depuis le dossier du dépôt, avec Python 3.11 ou plus récent :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lite.txt
scripts/run_lite.sh
```

Le lanceur affiche l’adresse locale choisie (port préféré 8510).
Le script Lite utilise le verrou mono-instance existant. Fermer les autres
instances SMART/FULL avant un essai sur la même base. Une session navigateur
supplémentaire dans le même processus partage le travail en cours.

Pour essayer sans utiliser la base habituelle :

```bash
PIS_DB_PATH="$HOME/.pis-trials/lite-mvp/files.db" scripts/run_lite.sh
```

L’installation Lite ne nécessite ni Ollama, ni torch, ni sentence-transformers,
ni PostgreSQL, ni Redis. La base effective est visible dans la barre latérale.

## Parcours quotidien

1. **Scanner** : saisir un dossier existant, puis lancer le scan. Commencer avec
   un petit dossier représentatif. Le scan inventorie les métadonnées et les
   chemins, enregistre par lots et affiche le nombre de fichiers traités.
2. **Extraire** : traiter le prochain lot (100 fichiers par défaut, 1 000 au
   maximum). Le dernier dossier scanné dans cette session constitue le périmètre.
   Sans dossier sélectionné dans la session, le périmètre est la base entière.
3. **Search** : chercher des mots dans les noms ou le contenu, filtrer par
   extension, déplier un résultat pour consulter son chemin et son texte.
4. **État du système** : voir les erreurs d’extraction et sauvegarder l’index.

La recherche affiche au maximum 100 résultats. L’aperçu textuel est limité à
12 000 caractères. « Ouvrir le dossier » agit sur la machine qui héberge PISS.
La navigation Lite est fixe : les variables `PIS_FEATURE_*` conservent leur
contrat pour les services mais n’ajoutent pas d’écrans avancés au MVP.

## Formats et limites

- Extraction : TXT, Markdown, PDF avec texte, DOCX et XLSX.
- Taille d’extraction : de 1 octet à 50 Mo. Les fichiers vides et plus grands
  restent inventoriés mais ne sont pas extraits dans ce parcours.
- Les formats hors périmètre restent recherchables par leur nom s’ils sont
  indexés. Les dossiers techniques et fichiers exclus par le scanner existant
  restent exclus (environnements virtuels, caches, fichiers système, etc.).
- Les PDF sans texte et les documents invalides produisent un état explicite
  dans la file d’erreurs canonique. Aucune conversion cloud n’est utilisée.
- Arrêter le scan conserve les fichiers déjà enregistrés sans marquer les
  fichiers non visités comme disparus. Relancer effectue un nouveau passage
  incrémental ; il ne reprend pas un curseur exact dans l’arborescence.
- Arrêter l’extraction prend effet entre deux fichiers. Un parseur actif peut
  terminer avant l’arrêt ; il n’est pas interrompu de force et aucun délai
  maximal par document n’est garanti.
- Au démarrage du processus Lite, les scans abandonnés sont marqués FAILED,
  sans réconciliation. Les nouveaux onglets réutilisent le worker partagé.
- Une erreur de parcours ou d’accès à un fichier fait échouer le scan et
  protège les états existants contre une fausse déclaration de disparition.
- La sauvegarde copie l’index SQLite avec son manifeste, sans les sources ni
  les embeddings. Elle est synchrone ; une grosse base peut bloquer l’écran
  pendant la copie. La restauration demeure disponible via le CLI existant.

Les sources ne sont pas réécrites par le scan ou l’extraction. Conserver l’index
et les sauvegardes hors des dossiers sources pour distinguer les données de
travail des documents recherchés.

## Validation

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest tests/ui/test_lite_mvp.py
```

Ces tests utilisent l’application canonique avec les vrais boutons Streamlit,
un corpus temporaire et les extracteurs réels : cinq formats, document invalide,
recherche dans le contenu, nouvelle session, sauvegarde vérifiée, sources
inchangées, dossier invalide/vide, requêtes malformées, scan incrémental,
modification, suppression, arrêt du worker, nouvel onglet, récupération après
interruption, erreurs de parcours et d’accès.

La validation en conteneur ne remplace pas la recette sur Kubuntu : vérifier
l’ouverture du gestionnaire de fichiers, les montages de disques, les droits
réels et les performances sur un corpus représentatif avant un scan massif.

Validation du 3 octobre 2026 : 8 tests Lite réussis dans un environnement Python
3.12 vierge installé avec `requirements-lite.txt` + pytest ; 103 tests ciblés et
de régression réussis dans l’environnement de validation (scan, extraction,
recherche, profils, sauvegarde, UI SMART/FULL et release UI). Compilation et
contrôle des espaces réussis ; Ruff F/I réussi sur les nouveaux modules et
tests. Démarrage du serveur vérifié : réponse HTTP 200 « ok » sur son endpoint
de santé. La suite complète du dépôt, le navigateur réel, Python 3.11 et le
corpus personnel multi-disques n’ont pas été qualifiés dans cette livraison.
