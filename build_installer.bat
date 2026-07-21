@echo off
setlocal

echo === Step 1/2: building ZapretDrum.exe ===
call build_exe.bat NOPAUSE
if errorlevel 1 (
    echo ERROR: build_exe.bat failed, see above.
    pause
    exit /b 1
)

echo.
echo === Step 2/2: building the installer (ZapretDrum-Setup.exe) ===

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo Inno Setup was not found on this computer.
    echo.
    echo It's a free tool that turns the .exe into a proper installer
    echo ^(with a folder picker, Start Menu entry, desktop icon and uninstaller^).
    echo.
    echo 1. Download it from: https://jrsoftware.org/isdl.php
    echo 2. Install it ^(default options are fine^)
    echo 3. Run this script again
    echo.
    echo In the meantime, dist\ZapretDrum.exe already works on its own.
    pause
    exit /b 1
)

"%ISCC%" installer\setup.iss
if errorlevel 1 (
    echo ERROR: Installer build failed, see output above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Done! Installer ready at: installer\Output\ZapretDrum-Setup.exe
echo  This single file is what you send to friends.
echo ============================================================
pause
