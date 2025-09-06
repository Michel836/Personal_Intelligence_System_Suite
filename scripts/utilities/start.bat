@echo off
echo ========================================
echo  36TB Intelligence - Quick Start
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found! Please install Python 3.11+
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Check if requirements are installed
if not exist ".venv\pyvenv.cfg" (
    echo ERROR: Virtual environment setup failed
    pause
    exit /b 1
)

REM Install requirements if needed
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Installing requirements...
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install requirements
        pause
        exit /b 1
    )
)

REM Create data directories
if not exist "data" mkdir data
if not exist "data\cache" mkdir data\cache
if not exist "data\indexes" mkdir data\indexes
if not exist "data\reports" mkdir data\reports
if not exist "data\logs" mkdir data\logs

REM Check for .env file
if not exist ".env" (
    if exist ".env.example" (
        echo Copying .env.example to .env
        copy .env.example .env
        echo.
        echo IMPORTANT: Please edit .env file with your configuration!
        echo.
    ) else (
        echo WARNING: No .env file found!
    )
)

echo ========================================
echo  Setup Complete!
echo ========================================
echo.
echo Available commands:
echo   1. Quick scan test: python scripts\quick_scan.py C: 1000
echo   2. Verify install:  python scripts\verify_installation.py
echo   3. Start UI:        streamlit run src\ui\app.py
echo.

REM Ask user what to do
set /p choice="What would you like to do? (1/2/3): "

if "%choice%"=="1" (
    echo Running quick scan test...
    python scripts\quick_scan.py C: 1000
) else if "%choice%"=="2" (
    echo Verifying installation...
    python scripts\verify_installation.py
) else if "%choice%"=="3" (
    echo Starting Streamlit UI...
    streamlit run src\ui\app.py
) else (
    echo Invalid choice. Opening command prompt in virtual environment.
)

echo.
echo Virtual environment is activated. You can now run commands manually.
cmd /k