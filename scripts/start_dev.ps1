# ==============================================================================
# Anti-Proxy Attendance System - Development Startup Script
# Starts:
#   1. Docker Compose (MongoDB on 27017, FastAPI Backend on 8000, React Frontend on 3000)
#   2. Native Windows Vision Agent (run_local_webcam.py on port 8088 in standby mode)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_dev.ps1
# ==============================================================================

param(
    [string]$CameraIndex = "auto",
    [switch]$NoVision,
    [switch]$ForegroundVision
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  ANTI-PROXY ATTENDANCE SYSTEM - STARTUP" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Ensure Docker is running
Write-Host "`n[1/3] Starting Docker Compose services (MongoDB, Backend, Frontend)..." -ForegroundColor Yellow
try {
    docker info > $null 2>&1
} catch {
    Write-Host "ERROR: Docker daemon is not running. Please start Docker Desktop first." -ForegroundColor Red
    exit 1
}

docker compose up -d mongodb backend frontend
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to start Docker Compose services." -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Docker containers running." -ForegroundColor Green

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
    Write-Host "  ✓ Backend API is healthy." -ForegroundColor Green
} else {
    Write-Host "  ! Warning: Backend healthcheck timed out. Proceeding..." -ForegroundColor DarkYellow
}

# 3. Start Native Vision Agent
if (-not $NoVision) {
    Write-Host "`n[3/3] Checking Native Windows Vision Agent..." -ForegroundColor Yellow
    $portActive = Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue

    if ($portActive) {
        Write-Host "  ✓ Vision Agent is ALREADY running on port 8088." -ForegroundColor Green
    } else {
        $pythonExe = Join-Path $ProjectRoot "vision-service\.venv\Scripts\python.exe"
        if (-not (Test-Path $pythonExe)) {
            $pythonExe = "python"
        }
        $visionScript = Join-Path $ProjectRoot "vision-service\run_local_webcam.py"

        if ($ForegroundVision) {
            Write-Host "  Starting Vision Agent in foreground..." -ForegroundColor Cyan
            & $pythonExe $visionScript --camera-index $CameraIndex
        } else {
            Write-Host "  Starting Vision Agent in background (Standby mode)..." -ForegroundColor Cyan
            Start-Process -FilePath $pythonExe -ArgumentList "$visionScript --camera-index $CameraIndex" -WindowStyle Hidden
            Start-Sleep -Seconds 3
            Write-Host "  ✓ Vision Agent launched in background." -ForegroundColor Green
        }
    }
}

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "  SYSTEM READY FOR CLASSROOM ATTENDANCE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Teacher ERP Portal : http://localhost:3000" -ForegroundColor White
Write-Host "  FastAPI Backend    : http://localhost:8000" -ForegroundColor White
Write-Host "  Vision Agent API   : http://localhost:8088" -ForegroundColor White
Write-Host "  Camera Status      : STANDBY (Turns on automatically on 'Take Attendance')" -ForegroundColor Cyan
Write-Host ""
Write-Host "Instructions:" -ForegroundColor Yellow
Write-Host "  1. Open http://localhost:3000 in your browser."
Write-Host "  2. Log in as Teacher (teacher@demo.edu / TeacherDevPass123!)."
Write-Host "  3. Select Class (e.g., DS-B) and click 'Take Attendance'."
Write-Host "  4. The physical webcam will turn ON automatically and live stream starts."
Write-Host "  5. Click 'End Attendance & Finalize' to release the webcam."
Write-Host ""
