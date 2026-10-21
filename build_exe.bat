@echo off
setlocal
cd /d "%~dp0"
title Build Blox Fruits V4 Tracker

echo ================================================
echo   Building Blox Fruits V4 Tracker for Windows
echo ================================================
echo.

echo This build script uses Python 3.12 for a consistent Windows GUI build.
py -3.12 --version >nul 2>&1
if errorlevel 1 goto python_missing

py -3.12 --version

echo.
echo Installing build dependencies...
py -3.12 -m pip install --upgrade pip
if errorlevel 1 goto failed
py -3.12 -m pip install -r requirements-build.txt
if errorlevel 1 goto failed

echo.
echo Building the standalone EXE...
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name "Blox Fruits V4 Tracker" --icon "app_icon.ico" --version-file "version_info.txt" --add-data "app_icon.ico;." main.py
if errorlevel 1 goto failed

if not exist "dist\Blox Fruits V4 Tracker.exe" goto missing_exe
for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath 'dist\Blox Fruits V4 Tracker.exe').Hash.ToLower()"') do set "HASH=%%H"
echo %HASH%  Blox Fruits V4 Tracker.exe>"dist\SHA256SUMS.txt"

echo.
echo Build complete:
echo %CD%\dist\Blox Fruits V4 Tracker.exe
echo.
echo SHA-256:
echo %HASH%
echo.
echo Note: the EXE is not digitally signed unless you use a trusted code-signing certificate.
echo See SIGNING.md for details.
echo.
pause
exit /b 0

:python_missing
echo ERROR: Python 3.12 was not found by the Python launcher.
echo Install 64-bit Python 3.12, or use the GitHub Actions workflow to build the EXE automatically.
echo https://www.python.org/downloads/
echo.
pause
exit /b 1

:missing_exe
echo ERROR: PyInstaller reported success, but the EXE was not found in dist.
goto failed

:failed
echo.
echo Build failed. Read the error above. Existing user data in AppData is not changed.
echo.
pause
exit /b 1
