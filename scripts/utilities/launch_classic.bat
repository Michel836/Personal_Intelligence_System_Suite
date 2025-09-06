@echo off
echo 🔍 36TB Intelligence - Version Classique
echo =======================================
echo.
echo Demarrage de l'interface classique...
echo.

cd /d "%~dp0"
streamlit run src/ui/app.py

echo.
pause