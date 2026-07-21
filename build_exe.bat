@echo off
setlocal

echo Checking Python...
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found in PATH. Install Python 3.10+ from https://python.org and try again.
    goto :end_error
)

echo Installing/updating dependencies (this may take a minute)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    goto :end_error
)

echo.
echo Building ZapretDrum.exe with PyInstaller...
python -m PyInstaller --noconfirm --onefile --windowed --name ZapretDrum --uac-admin ^
    --icon=assets\icon.ico ^
    --add-data "assets\icon.ico;assets" ^
    --add-data "VERSION;." ^
    main.py
if errorlevel 1 (
    echo ERROR: Build failed, see the output above.
    goto :end_error
)

echo.
echo Done! The file is at dist\ZapretDrum.exe
if /I not "%~1"=="NOPAUSE" pause
exit /b 0

:end_error
if /I not "%~1"=="NOPAUSE" pause
exit /b 1
