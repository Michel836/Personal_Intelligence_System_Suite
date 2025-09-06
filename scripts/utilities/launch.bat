@echo off
title 36TB Intelligence - Launcher
color 0A

echo.
echo     ██████╗  ██████╗ ████████╗██████╗     ██╗███╗   ██╗████████╗███████╗██╗     ██╗     ██╗ ██████╗ ███████╗███╗   ██╗ ██████╗███████╗
echo     ╚════██╗██╔════╝ ╚══██╔══╝██╔══██╗    ██║████╗  ██║╚══██╔══╝██╔════╝██║     ██║     ██║██╔════╝ ██╔════╝████╗  ██║██╔════╝██╔════╝
echo      █████╔╝███████╗    ██║   ██████╔╝    ██║██╔██╗ ██║   ██║   █████╗  ██║     ██║     ██║██║  ███╗█████╗  ██╔██╗ ██║██║     █████╗  
echo      ╚═══██╗██╔═══██╗   ██║   ██╔══██╗    ██║██║╚██╗██║   ██║   ██╔══╝  ██║     ██║     ██║██║   ██║██╔══╝  ██║╚██╗██║██║     ██╔══╝  
echo     ██████╔╝╚██████╔╝   ██║   ██████╔╝    ██║██║ ╚████║   ██║   ███████╗███████╗███████╗██║╚██████╔╝███████╗██║ ╚████║╚██████╗███████╗
echo     ╚═════╝  ╚═════╝    ╚═╝   ╚═════╝     ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚══════╝╚══════╝╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝ ╚═════╝╚══════╝
echo.
echo                                          🔍 Personal Knowledge Operating System
echo.
echo ================================================================================================================
echo.
echo Choisissez votre version d'interface:
echo.
echo   [1] Version Classique  - Interface standard avec toutes les fonctionnalites
echo   [2] Version Moderne    - Interface ergonomique avec design moderne
echo   [3] Quitter
echo.
set /p choice="Votre choix (1, 2 ou 3): "

if "%choice%"=="1" (
    echo.
    echo 🔍 Lancement de la version classique...
    call launch_classic.bat
) else if "%choice%"=="2" (
    echo.
    echo 🚀 Lancement de la version moderne...
    call launch_modern.bat
) else if "%choice%"=="3" (
    echo.
    echo Aurevoir!
    timeout /t 2 >nul
    exit
) else (
    echo.
    echo Choix invalide. Relancement du menu...
    timeout /t 2 >nul
    goto :eof
    call launch.bat
)

pause