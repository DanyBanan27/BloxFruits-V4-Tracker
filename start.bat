@echo off
setlocal
cd /d "%~dp0"
title Blox Fruits V4 Tracker

echo ================================================
echo        Blox Fruits V4 Tracker 2.3.0
echo ================================================
echo.

echo This source launcher uses Python 3.12 for a consistent GUI runtime.
py -3.12 --version >nul 2>&1
if errorlevel 1 goto no_python
py -3.12 --version

echo.
echo Checking PyQt6...
py -3.12 -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo PyQt6 not found. Installing required libraries...
    py -3.12 -m pip install -r requirements.txt
    if errorlevel 1 goto install_error
)

echo.
echo Starting the application...
echo If it fails, the error will remain visible below.
echo.
py -3.12 main.py
set "APP_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%APP_EXIT_CODE%"=="0" (
    echo The program finished with error code %APP_EXIT_CODE%.
    echo Please take a screenshot of the error above.
) else (
    echo The program has closed.
)
echo.
pause
exit /b %APP_EXIT_CODE%

:no_python
echo ERROR: Python 3.12 was not found by the Python launcher.
echo Install 64-bit Python 3.12, or download the standalone EXE from GitHub Releases.
echo https://www.python.org/downloads/
echo.
pause
exit /b 1

:install_error
echo.
echo ERROR: Could not install the required libraries.
echo Check your connection, then run: py -3.12 -m pip install -r requirements.txt
echo.
pause
exit /b 1
