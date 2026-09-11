<#
.SYNOPSIS
    Task 100B -- start TalonX under the unified runtime supervisor.
.DESCRIPTION
    Thin wrapper around `python -m talonx_ops.supervisor run`. The supervisor
    owns start / health / restart policy / controlled stop / dependency order
    for the four TalonX processes:

        original      run_talonx.py                                   (MANDATORY)
        experimental  python -m talonx_signals.run                    (OPTIONAL)
        intelligence  python -m talonx_ingest.intelligence.service poll --with-backfill   (OPTIONAL)
        dashboard     dashboard_web.py                                (OPTIONAL)

    It does NOT change any process's own internals -- it launches the existing
    entrypoints as child processes and watches them. An OPTIONAL component
    crashing never kills Original; the supervisor restarts it with bounded
    backoff. Ctrl+C triggers the Phase 14 controlled shutdown (experimental ->
    intelligence -> original -> dashboard, then EOD reconciliation persist,
    then orphan verification).

    Redis is still required by original + experimental exactly as before;
    ensure the talonx-redis container is up first (start_talonx.ps1 does this).
.PARAMETER NoDashboard
    Do not supervise dashboard_web.py.
.PARAMETER NoBackfill
    Launch the intelligence service without --with-backfill.
.EXAMPLE
    .\scripts\start_talonx_supervised.ps1
    .\scripts\start_talonx_supervised.ps1 -NoDashboard
#>
param(
    [switch]$NoDashboard,
    [switch]$NoBackfill
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$argsList = @("-m", "talonx_ops.supervisor", "run")
if ($NoDashboard) { $argsList += "--no-dashboard" }
if ($NoBackfill)  { $argsList += "--no-backfill" }

Write-Host "Starting TalonX supervisor: $py $($argsList -join ' ')"
& $py @argsList
exit $LASTEXITCODE
