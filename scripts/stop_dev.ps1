# ==============================================================================
# Anti-Proxy Attendance System - Stop Script
# Stops:
#   1. Running vision agent python processes (releases port 8088 and webcam device)
#   2. Optionally stops Docker Compose services
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/stop_dev.ps1 [-StopDocker]
# ==============================================================================

param(
    [switch]$StopDocker
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "`n[1/2] Stopping Native Windows Vision Agent..." -ForegroundColor Yellow
# Find process listening on port 8088
$conn = Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue
if ($conn) {
    foreach ($c in $conn) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Write-Host "  ✓ Vision Agent on port 8088 stopped. Webcam handle released." -ForegroundColor Green
} else {
    Write-Host "  ✓ No vision agent was active on port 8088." -ForegroundColor Green
}

# Also ensure any lingering run_local_webcam processes are terminated
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*run_local_webcam.py*" } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

if ($StopDocker) {
    Write-Host "`n[2/2] Stopping Docker containers..." -ForegroundColor Yellow
    docker compose stop
    Write-Host "  ✓ Docker containers stopped." -ForegroundColor Green
} else {
    Write-Host "`n[2/2] Docker containers left running. (Use -StopDocker to also stop containers)" -ForegroundColor DarkGray
}

Write-Host "`nAll webcam devices released and free.`n" -ForegroundColor Green
