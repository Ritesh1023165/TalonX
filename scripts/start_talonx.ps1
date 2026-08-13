<#
.SYNOPSIS
    Starts run_talonx.py and the Streamlit dashboard together.
.DESCRIPTION
    Ensures the Redis container (docker-compose.yaml's talonx-redis) is
    up, then launches run_talonx.py and `streamlit run talonx_dispatch/app.py`
    using this repo's own .venv.

    dashboard_web.py is intentionally NOT included here -- start it
    separately with start_dashboard_web.ps1.

    Default (no -Interactive): both processes run HIDDEN, with
    stdout/stderr redirected to .run\logs\*.log. This is what
    register_scheduled_tasks.ps1's 10am task uses, since a scheduled task
    has no console to show a window in anyway.

    -Interactive: opens each process in its own visible console window
    instead, for when you're running this by hand from a terminal and
    want to watch the live output like you're used to.
.PARAMETER Interactive
    Show each process in its own visible window instead of hidden + logged to file.
.EXAMPLE
    .\scripts\start_talonx.ps1
    .\scripts\start_talonx.ps1 -Interactive
#>
param(
    [switch]$Interactive
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runDir = Join-Path $repoRoot ".run"
$logDir = Join-Path $runDir "logs"
$pidFile = Join-Path $runDir "talonx.pids.json"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython -- create it first (see README.md Section 4)."
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -Raw | ConvertFrom-Json
    $stillRunning = @($existing.PSObject.Properties | Where-Object {
        $_.Name -ne "started_at" -and (Get-Process -Id $_.Value -ErrorAction SilentlyContinue)
    })
    if ($stillRunning.Count -gt 0) {
        Write-Warning "TalonX already appears to be running (see $pidFile). Run stop_talonx.ps1 first if you want to restart it."
        exit 1
    }
}

# Ensure Redis (docker-compose.yaml's talonx-redis) is up -- idempotent,
# safe to run every time; a no-op if it's already running. Only a
# warning on failure, not fatal: run_talonx.py itself already degrades
# gracefully (logs once, keeps running) when Redis isn't reachable.
Write-Host "Ensuring Redis container is up..."
Push-Location $repoRoot
try {
    docker compose up -d talonx-redis 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "docker compose returned a non-zero exit code -- is Docker Desktop running?"
    }
} catch {
    Write-Warning "Could not start the Redis container via Docker (is Docker Desktop running?). Continuing anyway -- $_"
} finally {
    Pop-Location
}

# PYTHONUNBUFFERED, in addition to python's own -u flag below, so log
# files fill in near-real-time instead of sitting in Python's default
# block-buffered stdout until the buffer fills or the process exits --
# matters most for the hidden/scheduled case, where there's no console
# to notice output has "gone quiet."
$env:PYTHONUNBUFFERED = "1"

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$processes = [ordered]@{}

function Start-TalonxProcess {
    param([string]$Name, [string]$Arguments)

    if ($Interactive) {
        return Start-Process -FilePath $venvPython -ArgumentList $Arguments `
            -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
    }
    $outLog = Join-Path $logDir "$Name`_$timestamp.log"
    $errLog = Join-Path $logDir "$Name`_$timestamp.err.log"
    return Start-Process -FilePath $venvPython -ArgumentList $Arguments `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
}

Write-Host "Starting run_talonx.py..."
$runTalonx = Start-TalonxProcess -Name "run_talonx" -Arguments "-u run_talonx.py"
$processes["run_talonx"] = $runTalonx.Id

Write-Host "Starting Streamlit dashboard..."
$streamlit = Start-TalonxProcess -Name "streamlit" -Arguments "-u -m streamlit run talonx_dispatch\app.py"
$processes["streamlit"] = $streamlit.Id

$processes["started_at"] = (Get-Date).ToString("o")
$processes | ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8

Write-Host ""
Write-Host "Started. run_talonx PID=$($runTalonx.Id), streamlit PID=$($streamlit.Id)"
if (-not $Interactive) {
    Write-Host "Logs: $logDir"
}
Write-Host "Streamlit will be reachable at http://localhost:8501 once it finishes starting."
Write-Host "Stop with: .\scripts\stop_talonx.ps1"
