# AI Operations Center — Quick Start (PowerShell)
# Run this from the project root: .\start.ps1

$ErrorActionPreference = "SilentlyContinue"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   AI Operations Center v3.0 — Quick Start"         -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Kill any leftover servers on ports 3000 & 8000 ────────────────────────────
Write-Host "[0/2] Cleaning up old processes..." -ForegroundColor Yellow

# Kill processes on port 3000 (Next.js)
$port3000 = netstat -ano | Select-String ":3000 " | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -Unique
foreach ($process_id in $port3000) {
    if ($process_id -match '^\d+$' -and $process_id -ne "0") {
        taskkill /PID $process_id /F 2>$null | Out-Null
        Write-Host "   Killed PID $process_id (port 3000)" -ForegroundColor DarkGray
    }
}

# Kill processes on port 8000 (FastAPI)
$port8000 = netstat -ano | Select-String ":8000 " | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -Unique
foreach ($process_id in $port8000) {
    if ($process_id -match '^\d+$' -and $process_id -ne "0") {
        taskkill /PID $process_id /F 2>$null | Out-Null
        Write-Host "   Killed PID $process_id (port 8000)" -ForegroundColor DarkGray
    }
}

Start-Sleep -Seconds 1
Write-Host "   Ports cleared." -ForegroundColor Green
Write-Host ""

# ── Check .env ────────────────────────────────────────────────────────────────
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[ERROR] .env file not found. Copy .env.example and fill in your API keys." -ForegroundColor Red
    exit 1
}

$groqKey = (Get-Content $envFile | Where-Object { $_ -match "^GROQ_API_KEY=" }) -replace "GROQ_API_KEY=", ""
if (-not $groqKey -or $groqKey -match "your_") {
    Write-Host "[WARN]  GROQ_API_KEY is not set in .env. Backend may fail." -ForegroundColor Yellow
}

# ── Start Backend ─────────────────────────────────────────────────────────────
Write-Host "[1/2] Starting FastAPI backend on http://localhost:8000 ..." -ForegroundColor Green
$backendDir = Join-Path $Root "backend"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$backendDir'; python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
) -WindowStyle Normal

Start-Sleep -Seconds 3

# ── Start Frontend ─────────────────────────────────────────────────────────────
Write-Host "[2/2] Starting Next.js frontend on http://localhost:3000 ..." -ForegroundColor Green
$frontendDir = Join-Path $Root "frontend"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$frontendDir'; npm run dev -- --port 3000"
) -WindowStyle Normal

Write-Host ""
Write-Host "✓ Both services started in separate windows." -ForegroundColor Green
Write-Host ""
Write-Host "  Backend  → http://localhost:8000" -ForegroundColor Cyan
Write-Host "  Frontend → http://localhost:3000" -ForegroundColor Cyan
Write-Host "  API Docs → http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Tip: Next time just run .\start.ps1 — it auto-cleans old servers." -ForegroundColor DarkGray
Write-Host ""
Write-Host "Press any key to exit this launcher..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
