@echo off
echo 🚀 36TB Intelligence - Version Moderne  
echo =======================================
echo.
echo Demarrage de l'interface moderne...
echo.

cd /d "%~dp0"
streamlit run src/ui/modern_app.py

echo.
pause