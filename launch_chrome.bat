@echo off
setlocal enabledelayedexpansion
title Instagram Reel Investigation Agent - Chrome Launcher

echo ======================================================================
echo    INSTAGRAM REEL INVESTIGATION AGENT - CHROME CDP LAUNCHER
echo ======================================================================
echo.

:: Check if port 9222 is already listening
netstat -ano | findstr /R ":9222.*LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Chrome remote debugging is ALREADY ACTIVE on port 9222!
    echo You can now run 'python main.py' to start the agent.
    echo.
    pause
    exit /b 0
)

:: Find Chrome binary path
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

:: Check if chrome.exe is currently running without port 9222
tasklist /FI "IMAGENAME eq chrome.exe" 2>NUL | find /I /N "chrome.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [WARNING] Chrome is currently running without remote debugging enabled.
    echo To allow the agent to connect to your existing session:
    echo 1. Please close your current Chrome window(s).
    echo 2. Press any key in this window to relaunch Chrome with debugging enabled.
    echo    (Your open tabs and Instagram session will be restored automatically)
    echo.
    pause
    taskkill /F /IM chrome.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo Starting Google Chrome with Remote Debugging on port 9222...
start "" "%CHROME_BIN%" --remote-debugging-port=9222 --remote-allow-origins=* --restore-last-session "https://www.instagram.com/reels/"

timeout /t 3 /nobreak >nul
netstat -ano | findstr /R ":9222.*LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] Chrome launched and listening on http://127.0.0.1:9222!
    echo Log in to Instagram if needed, browse to Reels, and then start:
    echo   python main.py
    echo.
) else (
    echo.
    echo [INFO] Chrome started. Please confirm port 9222 is open before starting main.py.
)

pause

