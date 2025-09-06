@echo off
echo === Correction des permissions Ollama ===
echo.

echo IMPORTANT: Ce script doit etre execute en tant qu'ADMINISTRATEUR
echo.
echo 1. Clic droit sur ce fichier
echo 2. "Executer en tant qu'administrateur"
echo.
pause

echo Verification des permissions administrateur...
net session >nul 2>&1
if %errorLevel% == 0 (
    echo OK - Droits administrateur detectes
) else (
    echo ERREUR - Droits administrateur requis !
    echo Clic droit sur ce fichier et "Executer en tant qu'administrateur"
    pause
    exit /b 1
)

echo.
echo Liberation du port 11434...
netsh int ipv4 set global tcpchimney=disabled
netsh int ipv4 set global rss=disabled
netsh int ipv4 set global autotuninglevel=disabled

echo.
echo Arret de tous les processus Ollama...
taskkill /f /im ollama.exe 2>nul
timeout /t 3 /nobreak >nul

echo.
echo Verification du port 11434...
netstat -an | findstr 11434

echo.
echo Demarrage d'Ollama en tant qu'administrateur...
start /B ollama serve

echo.
echo Attente du demarrage...
timeout /t 10 /nobreak >nul

echo.
echo Test de connexion...
ollama list

echo.
echo Si aucune erreur, Ollama fonctionne !
echo Vous pouvez maintenant fermer cette fenetre et utiliser Ollama.
pause