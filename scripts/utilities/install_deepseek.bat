@echo off
cls
echo ================================================
echo     INSTALLATION DEEPSEEK-R1:8B AVEC OLLAMA
echo ================================================
echo.
echo DeepSeek-R1 8B - Modele de raisonnement avance
echo Taille: ~4.7 GB
echo RAM requise: 8-16 GB
echo.
pause

echo.
echo [1/4] Verification d'Ollama...
ollama --version
if %errorlevel% neq 0 (
    echo ERREUR: Ollama n'est pas accessible
    echo Verifiez que le service Ollama est demarre
    pause
    exit /b 1
)

echo.
echo [2/4] Telechargement de DeepSeek-R1 8B...
echo Cela peut prendre 5-10 minutes selon votre connexion...
echo.

ollama pull deepseek-r1:8b

if %errorlevel% equ 0 (
    echo.
    echo [3/4] Modele telecharge avec succes !
    echo.
    echo Verification...
    ollama list
    
    echo.
    echo [4/4] Test du modele...
    ollama run deepseek-r1:8b "Bonjour, je suis ton assistant IA pour explorer 36TB de documents. Comment puis-je t'aider?"
    
) else (
    echo.
    echo ERREUR lors du telechargement.
    echo Essayons une alternative...
    echo.
    ollama pull deepseek:latest
)

echo.
echo ================================================
echo          CONFIGURATION TERMINEE
echo ================================================
echo.
echo DeepSeek-R1 est maintenant pret !
echo.
echo Pour l'utiliser avec votre systeme:
echo 1. Lancez: streamlit run src/ui/app.py
echo 2. Allez a la page "AI Chat"
echo 3. Conversez avec vos documents !
echo.
pause