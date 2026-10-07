# ==============================================================================
# Anti-Proxy Attendance System - Development Startup Script
# Architecture:
#   - MongoDB on 27017, FastAPI Backend on 8000, React Frontend on 3000
#   - Vision service (SCRFD + ArcFace) inside the Compose network only; it has
#     no published port and is called by the backend
#   - Browser directly owns physical PC / USB webcam via getUserMedia()
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_dev.ps1
# ==============================================================================

param()

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  ANTI-PROXY ATTENDANCE SYSTEM - STARTUP" -ForegroundColor Cyan
Write-Host "  Architecture: Browser-Owned Webcam + SCRFD/ArcFace Bridge" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Ensure Docker is running
Write-Host "`n[1/3] Starting Docker Compose services (MongoDB, Backend, Vision, Frontend)..." -ForegroundColor Yellow
try {
    docker info > $null 2>&1
} catch {
    Write-Host "ERROR: Docker daemon is not running. Please start Docker Desktop first." -ForegroundColor Red
    exit 1
}

docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to start Docker Compose services." -ForegroundColor Red
    Write-Host "       If the message mentions RECOGNITION_SIGNING_KEY, set a real value in .env (see README)." -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Docker containers running." -ForegroundColor Green

# 2. Wait for backend health
Write-Host "`n[2/3] Verifying Backend API health (http://localhost:8000/health)..." -ForegroundColor Yellow
$backendHealthy = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($resp.status -eq "healthy") {
            $backendHealthy = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}

if ($backendHealthy) {
    Write-Host "  [OK] Backend API is healthy." -ForegroundColor Green
} else {
    Write-Host "  ! Warning: Backend healthcheck timed out. Proceeding..." -ForegroundColor DarkYellow
}

Write-Host "`n[3/3] Camera architecture" -ForegroundColor Yellow
Write-Host "  [OK] Browser owns physical webcam directly via navigator.mediaDevices.getUserMedia()" -ForegroundColor Green
Write-Host "  [OK] Zero camera conflicts: Native Python never locks Windows video devices" -ForegroundColor Green
Write-Host "  [OK] Built-in PC webcam and USB webcams supported natively in browser" -ForegroundColor Green

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "  SYSTEM READY FOR ATTENDANCE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Teacher ERP Portal : http://localhost:3000" -ForegroundColor White
Write-Host "  FastAPI Backend    : http://localhost:8000" -ForegroundColor White
Write-Host "  Vision service     : internal only (no published port)" -ForegroundColor White
Write-Host "  Camera Mode        : BROWSER-OWNED (Activates on 'Take Attendance')" -ForegroundColor Cyan
Write-Host ""
Write-Host "Workflow:" -ForegroundColor Yellow
Write-Host "  1. Open http://localhost:3000 in Chrome / browser."
Write-Host "  2. Log in as Teacher (teacher@demo.edu / TeacherDevPass123!)."
Write-Host "  3. Select Class (e.g., DS-B) and click 'Take Attendance'."
Write-Host "  4. Chrome requests camera permission -> Physical webcam turns ON."
Write-Host "  5. Live video stream appears directly in ERP -> AI marks students PRESENT."
Write-Host "  6. Click 'End Attendance & Finalize' -> Browser releases camera immediately."
Write-Host ""
