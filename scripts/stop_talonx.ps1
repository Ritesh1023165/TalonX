<#
.SYNOPSIS
    Stops run_talonx.py and the Streamlit dashboard started by start_talonx.ps1.
.DESCRIPTION
    Forceful stop (Stop-Process) using the PIDs recorded in
    .run\talonx.pids.json by start_talonx.ps1. run_talonx.py's own
    cleanup (closing SQLite connections) is skipped, but SQLite's WAL
    mode already tolerates this the same way it tolerates a closed
    terminal window or a power loss -- an accepted tradeoff for a
    simple, reliable scheduled stop.

    Does NOT touch the Redis container -- that's managed separately via
    docker compose and is left running.
#>

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $repoRoot ".run\talonx.pids.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "No PID file found at $pidFile -- nothing tracked as running."
    exit 0
}

$tracked = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($prop in $tracked.PSObject.Properties) {
    if ($prop.Name -eq "started_at") { continue }
    $trackedId = $prop.Value
    $proc = Get-Process -Id $trackedId -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping $($prop.Name) (PID $trackedId)..."
        Stop-Process -Id $trackedId -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "$($prop.Name) (PID $trackedId) already stopped."
    }
}

Remove-Item $pidFile -Force
Write-Host "Done."
