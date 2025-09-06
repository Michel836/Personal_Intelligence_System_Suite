@echo off
cls
echo ================================================
echo       INSTALLATION LM STUDIO (RECOMMANDE)
echo ================================================
echo.
echo LM Studio est la meilleure alternative a Ollama pour Windows
echo - Interface graphique simple
echo - Compatible avec beaucoup de modeles
echo - Serveur API integre
echo - Fonctionne bien sur Windows
echo.

echo Etapes d'installation:
echo.
echo 1. TELECHARGER LM STUDIO:
echo    https://lmstudio.ai/
echo.
echo 2. INSTALLER le fichier .exe telecharge
echo.
echo 3. LANCER LM Studio
echo.
echo 4. TELECHARGER un modele recommande:
echo    - Mistral-7B-Instruct (excellent francais)
echo    - Zephyr-7B (conversations naturelles)
echo    - CodeLlama-7B (documents techniques)
echo.
echo 5. DEMARRER le serveur local dans LM Studio
echo    (onglet "Local Server" -> Start Server)
echo.
echo 6. TESTER l'integration:
echo    python test_lmstudio_integration.py
echo.

pause

echo.
echo ================================================
echo     CONFIGURATION AUTOMATIQUE DE L'INTEGRATION
echo ================================================
echo.

echo Installation des dependances Python...
pip install requests

echo.
echo Modification du ChatEngine pour utiliser LM Studio...

echo.
echo Une fois LM Studio installe et un modele telecharge:
echo 1. Demarrez le serveur local dans LM Studio
echo 2. Lancez: python test_lmstudio_integration.py
echo 3. Si OK: streamlit run src/ui/app.py
echo.
echo Votre chat IA utilisera alors LM Studio au lieu d'Ollama !
echo.
pause