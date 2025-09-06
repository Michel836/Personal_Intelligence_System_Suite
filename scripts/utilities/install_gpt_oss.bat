@echo off
cls
echo ================================================
echo     INSTALLATION GPT-OSS 12B AVEC OLLAMA
echo ================================================
echo.
echo ATTENTION: Ce modele necessite environ 8-10 GB d'espace disque
echo et 16 GB de RAM minimum pour fonctionner correctement.
echo.
pause

echo.
echo Etape 1: Verification d'Ollama...
ollama --version
if %errorlevel% neq 0 (
    echo ERREUR: Ollama n'est pas installe ou accessible
    echo Installez d'abord Ollama depuis: https://ollama.ai/download
    pause
    exit /b 1
)

echo.
echo Etape 2: Recherche des modeles disponibles similaires...
echo.

echo Les modeles open source recommandes pour votre usage:
echo.
echo [1] mistral:7b-instruct - Excellent en francais (4.1 GB)
echo [2] mixtral:8x7b - Plus puissant, multilingue (26 GB)
echo [3] llama2:13b - Modele puissant Meta (7.4 GB)
echo [4] codellama:13b - Specialise code et documents (7.4 GB)
echo [5] vicuna:13b - Alternative GPT performante (7.4 GB)
echo [6] orca2:13b - Microsoft, bon raisonnement (7.4 GB)
echo [7] solar:10.7b - Recent et performant (6.1 GB)
echo.
echo Note: GPT-OSS n'est pas directement disponible sur Ollama,
echo       mais ces modeles offrent des performances similaires.
echo.
echo Telechargement du modele recommande (Mistral 7B)...
echo.

ollama pull mistral:7b-instruct

echo.
echo Verification de l'installation...
ollama list

echo.
echo Test du modele...
ollama run mistral:7b-instruct "Bonjour, peux-tu m'aider a chercher dans mes documents?"

echo.
echo ================================================
echo Installation terminee !
echo Le modele est pret pour votre systeme 36TB Intelligence.
echo ================================================
pause