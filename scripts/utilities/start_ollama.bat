@echo off
echo Demarrage du service Ollama...
echo.

REM Tenter de demarrer Ollama en arriere-plan
start /B ollama serve

REM Attendre quelques secondes
timeout /t 5 /nobreak >nul

REM Verifier le statut
echo Verification du service...
ollama list

echo.
echo Si aucune erreur ci-dessus, Ollama est pret !
echo Maintenant telechargez un modele :
echo   ollama pull llama3.2:3b
echo.
pause