@echo off
cls
echo ================================================
echo          VALIDATION OLLAMA - FINAL
echo ================================================
echo.

echo [1/5] Verification de l'installation Ollama...
where ollama >nul 2>&1
if %errorlevel% equ 0 (
    echo    ✓ Ollama trouve dans PATH
    ollama --version 2>nul | findstr version
) else (
    echo    ✗ Ollama non trouve - reinstallation requise
    echo    Telechargez: https://ollama.ai/download
    pause
    exit /b 1
)

echo.
echo [2/5] Nettoyage des processus existants...
taskkill /f /im ollama.exe >nul 2>&1
timeout /t 3 /nobreak >nul
echo    ✓ Processus nettoyes

echo.
echo [3/5] Test de demarrage simple...
echo    Tentative de demarrage d'Ollama...
start /B ollama serve
timeout /t 8 /nobreak >nul

echo.
echo [4/5] Verification du service...
ollama list >nul 2>&1
if %errorlevel% equ 0 (
    echo    ✓ Service Ollama operationnel !
    echo    Modeles disponibles :
    ollama list
) else (
    echo    ⚠ Service non accessible
    echo    Tentative avec port alternatif...
    set OLLAMA_HOST=127.0.0.1:11435
    start /B ollama serve
    timeout /t 5 /nobreak >nul
    ollama list
)

echo.
echo [5/5] Test de telechargement de modele...
echo    Telechargement du modele llama3.2:1b (plus leger)...
ollama pull llama3.2:1b
if %errorlevel% equ 0 (
    echo    ✓ Modele telecharge avec succes !
) else (
    echo    ⚠ Echec du telechargement
)

echo.
echo ================================================
echo              RESULTAT FINAL
echo ================================================
ollama list
echo.
echo Si vous voyez des modeles ci-dessus, Ollama fonctionne !
echo Vous pouvez maintenant tester l'interface AI Chat.
echo.
pause