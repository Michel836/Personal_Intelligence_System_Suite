@echo off
cls
echo ================================================
echo      DEMARRAGE OLLAMA - SOLUTION DEFINITIVE
echo ================================================
echo.

echo IMPORTANT: Suivez ces etapes dans l'ordre
echo.

echo [1] ETAPE MANUELLE REQUISE:
echo     Ouvrez une NOUVELLE fenetre PowerShell et tapez:
echo.
echo     ollama serve
echo.
echo     (Laissez cette fenetre ouverte)
echo.
pause

echo.
echo [2] Test de connexion...
python test_ollama_connection.py

echo.
echo [3] Si OK, lancement de l'interface...
echo.
pause

streamlit run src/ui/app.py