<#
.SYNOPSIS
    Starts dashboard_web.py on its own -- separate from start_talonx.ps1.
.DESCRIPTION
    Independent of run_talonx.py/Streamlit: dashboard_web.py is a purely
    read-only view over the same Redis channels, so it can be started/
    stopped on its own schedule (or not scheduled at all -- run it
    manually whenever you want to watch live throughput).
.PARAMETER Interactive
    Show the process in its own visible window instead of hidden + logged to file.
.PARAMETER Port
    Passed straight through to dashboard_web.py's own --port (default 8787 there).
.EXAMPLE
    .\scripts\start_dashboard_web.ps1
    .\scripts\start_dashboard_web.ps1 -Interactive -Port 9000
#>
param(
    [switch]$Interactive,
    [int]$Port
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runDir = Join-Path $repoRoot ".run"
$logDir = Join-Path $runDir "logs"
$pidFile = Join-Path $runDir "dashboard_web.pid.json"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython -- create it first (see README.md Section 4)."
}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -Raw | ConvertFrom-Json
    if (Get-Process -Id $existing.pid -ErrorAction SilentlyContinue) {
        Write-Warning "dashboard_web.py already appears to be running (PID $($existing.pid)). Run stop_dashboard_web.ps1 first if you want to restart it."
        exit 1
    }
}

$env:PYTHONUNBUFFERED = "1"

$scriptArgs = "-u dashboard_web.py"
if ($Port) { $scriptArgs += " --port $Port" }

if ($Interactive) {
    $proc = Start-Process -FilePath $venvPython -ArgumentList $scriptArgs `
        -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
} else {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $outLog = Join-Path $logDir "dashboard_web_$timestamp.log"
    $errLog = Join-Path $logDir "dashboard_web_$timestamp.err.log"
    $proc = Start-Process -FilePath $venvPython -ArgumentList $scriptArgs `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
}

@{ pid = $proc.Id; started_at = (Get-Date).ToString("o") } |
    ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8

$effectivePort = if ($Port) { $Port } else { 8787 }
Write-Host "Started dashboard_web.py, PID=$($proc.Id)."
Write-Host "Browse to http://localhost:$effectivePort"
Write-Host "Stop with: .\scripts\stop_dashboard_web.ps1"
