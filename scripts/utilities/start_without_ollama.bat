@echo off
cls
echo ================================================
echo     36TB INTELLIGENCE - MODE SANS OLLAMA
echo ================================================
echo.
echo Demarrage du systeme en mode recherche avancee
echo (Chat IA desactive temporairement)
echo.

echo Installation des dependances...
pip install streamlit sentence-transformers pandas numpy loguru sqlalchemy rich

echo.
echo Lancement de l'interface...
echo.
echo FONCTIONNALITES DISPONIBLES:
echo  [OK] Scanner rapide (8000+ fichiers/sec)
echo  [OK] Recherche traditionnelle
echo  [OK] Recherche semantique IA
echo  [OK] Dashboard et statistiques
echo  [--] Chat IA (necessite Ollama)
echo.
echo Ouverture dans le navigateur...
streamlit run src/ui/app.py