# Instagram Reel Investigation Agent - PowerShell Chrome Launcher
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   INSTAGRAM REEL INVESTIGATION AGENT - CHROME CDP LAUNCHER" -ForegroundColor Cyan
Write-Host "======================================================================`n"

# 1. Check if port 9222 is already listening
$portCheck = Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue
if ($portCheck) {
    Write-Host "[OK] Chrome remote debugging is ALREADY ACTIVE on port 9222!" -ForegroundColor Green
    Write-Host "You can immediately run 'python main.py' to start the agent.`n"
    exit 0
}

# 2. Locate Chrome
$chromePaths = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chromeBin = $null
foreach ($path in $chromePaths) {
    if (Test-Path $path) {
        $chromeBin = $path
        break
    }
}

if (-not $chromeBin) {
    Write-Host "[ERROR] Google Chrome binary not found in standard directories!" -ForegroundColor Red
    exit 1
}

# 3. Check if chrome is running without debugging
$runningChrome = Get-Process chrome -ErrorAction SilentlyContinue
if ($runningChrome) {
    Write-Host "[WARNING] Chrome is currently running without remote debugging." -ForegroundColor Yellow
    Write-Host "Chromium requires restarting with debugging flags to enable CDP."
    $response = Read-Host "Close running Chrome and relaunch with debugging enabled? (y/n)"
    if ($response -match "^[yY]") {
        Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    } else {
        Write-Host "Aborted. Chrome must be launched with --remote-debugging-port=9222 for the agent to attach." -ForegroundColor Red
        exit 1
    }
}

# 4. Launch Chrome with flags
Write-Host "Launching Google Chrome on port 9222..." -ForegroundColor Cyan
Start-Process -FilePath $chromeBin -ArgumentList @(
    "--remote-debugging-port=9222",
    "--remote-allow-origins=*",
    "--disable-blink-features=AutomationControlled",
    "--restore-last-session",
    "https://www.instagram.com/reels/"
)

Start-Sleep -Seconds 3

$portCheckAfter = Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue
if ($portCheckAfter) {
    Write-Host "`n[SUCCESS] Chrome launched and listening on http://127.0.0.1:9222!" -ForegroundColor Green
    Write-Host "You can now run 'python main.py' to start the agent." -ForegroundColor Yellow
} else {
    Write-Host "`n[INFO] Chrome started. Ensure port 9222 is active before running main.py." -ForegroundColor Gray
}

