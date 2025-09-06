@echo off
cls
echo ================================================
echo     36TB INTELLIGENCE - DEMARRAGE COMPLET
echo ================================================
echo.

echo [1/3] Demarrage du service Ollama...
start /min cmd /k "ollama serve"
timeout /t 10 /nobreak >nul

echo.
echo [2/3] Verification du modele DeepSeek...
ollama list | findstr deepseek
if %errorlevel% neq 0 (
    echo Telechargement de DeepSeek-R1...
    ollama pull deepseek-r1
)

echo.
echo [3/3] Lancement de l'interface...
echo.
echo OUVERTURE DANS VOTRE NAVIGATEUR...
echo.
echo Pages disponibles:
echo  - Search: Recherche rapide
echo  - AI Search: Recherche semantique
echo  - AI Chat: Conversation avec DeepSeek
echo  - Dashboard: Vue d'ensemble
echo.
cd /d "%~dp0\..\.."
call .venv\Scripts\activate
python -m streamlit run src/ui/app.py