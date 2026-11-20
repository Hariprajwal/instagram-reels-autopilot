@echo off
setlocal enabledelayedexpansion
title Instagram Reel Investigation Agent - All-in-One Launcher

echo ======================================================================
echo    INSTAGRAM REEL INVESTIGATION AGENT - ALL-IN-ONE LAUNCHER
echo ======================================================================
echo.

:: 1. Check if Chrome remote debugging is already active on port 9222
netstat -ano | findstr /R ":9222.*LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Chrome remote debugging is already active on port 9222.
    goto launch_agent
)

:: 2. Find Google Chrome binary path
set "CHROME_BIN="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) else if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_BIN%"=="" (
    echo [ERROR] Google Chrome was not found in standard installation directories.
    echo Please ensure Google Chrome is installed.
    pause
    exit /b 1
)

:: Check if Chrome is already open without debugging port
tasklist /FI "IMAGENAME eq chrome.exe" 2>NUL | find /I /N "chrome.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [INFO] Chrome is running without port 9222. Restarting Chrome with debugging port...
    taskkill /F /IM chrome.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo [1/2] Launching Google Chrome on port 9222 (Reels)...
start "" "%CHROME_BIN%" --remote-debugging-port=9222 --remote-allow-origins=* --disable-blink-features=AutomationControlled --restore-last-session "https://www.instagram.com/reels/"

:: Wait up to 10 seconds for Chrome CDP port to open
echo [INFO] Waiting for Chrome remote debugging to initialize...
set /a attempts=0
:wait_port
timeout /t 1 /nobreak >nul
set /a attempts+=1
netstat -ano | findstr /R ":9222.*LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Chrome CDP ready on http://127.0.0.1:9222.
    goto launch_agent
)
if %attempts% lss 8 goto wait_port

echo [WARNING] Port 9222 not detected yet. Attempting to start agent anyway...

:launch_agent
echo.
echo ======================================================================
echo [2/2] STARTING INSTAGRAM REEL AGENT (python main.py)...
echo ======================================================================
echo.

python main.py

echo.
echo [INFO] Agent session has ended.
pause
