@echo off
cls
echo ================================================
echo   36TB INTELLIGENCE - MODE SANS CHAT IA
echo ================================================
echo.
echo Le chat IA necessite Ollama qui ne repond pas.
echo Mais toutes les autres fonctionnalites sont disponibles !
echo.

echo Lancement de l'interface...
echo.
echo FONCTIONNALITES DISPONIBLES:
echo  [✓] Scanner ultra-rapide (8000+ fichiers/sec)
echo  [✓] Recherche puissante (trouvez "michel")
echo  [✓] Recherche semantique IA
echo  [✓] Extraction PDF/Word
echo  [✓] Dashboard complet
echo  [✓] Statistiques detaillees
echo  [✗] Chat conversationnel (Ollama requis)
echo.

cd /d "%~dp0\..\.."
call .venv\Scripts\activate
python -m streamlit run src/ui/app.py