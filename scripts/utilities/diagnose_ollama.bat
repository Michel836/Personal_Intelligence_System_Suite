@echo off
echo === Diagnostic Ollama ===
echo.

echo 1. Verification des processus Ollama en cours...
tasklist | findstr /i ollama
echo.

echo 2. Tentative d'arret des processus existants...
taskkill /f /im ollama.exe 2>nul
timeout /t 2 /nobreak >nul
echo.

echo 3. Verification du port 11434...
netstat -an | findstr 11434
echo.

echo 4. Tentative de demarrage direct...
echo Demarrage d'Ollama en mode verbose...
ollama serve --verbose