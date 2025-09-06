@echo off
cls
echo ================================================
echo     RESOLUTION COMPLETE OLLAMA + DEEPSEEK
echo ================================================
echo.

echo [1/5] Nettoyage des processus bloques...
taskkill /f /im ollama.exe 2>nul
timeout /t 3 /nobreak >nul

echo.
echo [2/5] Liberation du port 11434...
netsh int ipv4 set global tcpchimney=disabled 2>nul
netsh int ipv4 set global rss=disabled 2>nul

echo.
echo [3/5] Demarrage d'Ollama en arriere-plan...
echo (Une nouvelle fenetre va s'ouvrir - NE PAS LA FERMER)
start cmd /k "ollama serve"

echo.
echo [4/5] Attente du demarrage (15 secondes)...
timeout /t 15 /nobreak

echo.
echo [5/5] Verification et installation DeepSeek...
ollama list
ollama pull deepseek-r1

echo.
echo ================================================
echo Si vous voyez DeepSeek dans la liste ci-dessus,
echo tout fonctionne !
echo.
echo IMPORTANT: Laissez la fenetre "ollama serve" ouverte
echo ================================================
pause