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
# safe to run every time; a no-op if it's already running.
#
# 2026-08-18 correctness fix (code-review finding #3/#7): previously a
# Redis startup failure here was only a Write-Warning, and the script
# proceeded to launch run_talonx.py regardless. That combined badly with
# RedisEventPublisher's OLD behavior (a failed connect() left it
# permanently disconnected, no retry -- separately fixed in
# talonx_ingest/events/publisher.py) to silently disable the live event
# bus for a whole session with no warning beyond a log line easy to miss
# in a hidden/scheduled-task run. `docker compose up -d` returning also
# does NOT mean the container is actually ready to accept connections yet
# (it returns once the container is CREATED, not once its healthcheck
# passes) -- so this now waits, bounded, for the container's own
# healthcheck (docker-compose.yaml's `redis-cli ping`) to report healthy,
# and ABORTS this script (does not launch run_talonx.py/Streamlit at all)
# if Redis isn't healthy within that window. This is fail-CLOSED for the
# NORMAL live startup path specifically -- run_talonx.py itself still
# degrades gracefully if Redis is lost mid-session (a separate, already-
# fixed concern), this only prevents KNOWINGLY starting a live session
# without its event bus in the first place.
Write-Host "Ensuring Redis container is up..."
Push-Location $repoRoot
$dockerUpFailed = $false
try {
    docker compose up -d talonx-redis 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        $dockerUpFailed = $true
    }
} catch {
    Write-Host "Could not run 'docker compose up' (is Docker Desktop running?) -- $_"
    $dockerUpFailed = $true
} finally {
    Pop-Location
}
if ($dockerUpFailed) {
    Write-Error "Aborting startup: 'docker compose up -d talonx-redis' failed -- not launching TalonX without its Redis event bus. Is Docker Desktop running?"
    exit 1
}

$redisReady = $false
$maxWaitSeconds = 30
$waited = 0
$health = "unknown"
Write-Host "Waiting for Redis to become healthy (up to ${maxWaitSeconds}s)..."
while ($waited -lt $maxWaitSeconds) {
    $health = docker inspect --format='{{.State.Health.Status}}' talonx-redis 2>$null
    if ($health -eq "healthy") {
        $redisReady = $true
        break
    }
    Start-Sleep -Seconds 2
    $waited += 2
}
if (-not $redisReady) {
    Write-Error "Aborting startup: Redis did not become healthy within ${maxWaitSeconds}s (last status: '$health'). Not launching TalonX without a working Redis event bus -- check 'docker compose logs talonx-redis' and retry once it's healthy."
    exit 1
}
Write-Host "Redis is healthy."

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
