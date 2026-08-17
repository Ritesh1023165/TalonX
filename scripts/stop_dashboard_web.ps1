<#
.SYNOPSIS
    Stops dashboard_web.py started by start_dashboard_web.ps1.
#>

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $repoRoot ".run\dashboard_web.pid.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "No PID file found at $pidFile -- nothing tracked as running."
    exit 0
}

$tracked = Get-Content $pidFile -Raw | ConvertFrom-Json
$proc = Get-Process -Id $tracked.pid -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "Stopping dashboard_web.py (PID $($tracked.pid))..."
    Stop-Process -Id $tracked.pid -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "dashboard_web.py (PID $($tracked.pid)) already stopped."
}

Remove-Item $pidFile -Force
Write-Host "Done."
