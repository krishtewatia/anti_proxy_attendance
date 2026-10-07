# ==============================================================================
# Anti-Proxy Attendance System - Stop Script
# Stops the Docker Compose services (MongoDB, backend, vision service, frontend).
# The browser owns the webcam, so there is no camera process to stop: the camera
# is released when the teacher ends attendance or closes the tab.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/stop_dev.ps1
# ==============================================================================

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Split-Path -Parent $ScriptDir)

Write-Host "`nStopping Docker containers..." -ForegroundColor Yellow
docker compose stop
Write-Host "  Docker containers stopped.`n" -ForegroundColor Green
