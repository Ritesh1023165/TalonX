# EVENT_RESPONSE_MAP_V1 Phase D runner (Windows Task Scheduler, S4U). NOT part of the design-lock fingerprint.
#   powershell -NoProfile -ExecutionPolicy Bypass -File run_phase_d.ps1 [-PreflightOnly]
# Writes one JSON line per step to results\event_response_map_v1\phase_d_runner.log:
#   START (utc, sha, fingerprint) -> PREFLIGHT -> [DOWNLOAD/RUN/CRASH/RESTART] -> END | ABORT
# Restart policy (documented in docs/research/preregistration/event_response_map_v1_nomination.md):
#   * the locked downloader is not symbol-resumable, so a failed download is retried ONCE from scratch (partial
#     archive moved aside; the SEC cache is reused by design);
#   * a scoring pass that crashed before its outputs were complete is re-executed ONCE (partial outputs moved aside),
#     recorded in this log and appended to report.md.
# The runner never pushes to git and never touches the live worktree.
param([switch]$PreflightOnly)
$ErrorActionPreference = 'Stop'
$WT   = 'C:\workspace\TalonX-erm'
$PY   = 'C:\workspace\TalonX\.venv\Scripts\python.exe'
$GIT  = 'C:\Program Files\Git\cmd\git.exe'
$OUT  = Join-Path $WT 'results\event_response_map_v1'
$LOG  = Join-Path $OUT 'phase_d_runner.log'
$EXPECT_FP   = '94013b3e8f3999b10de7beabf35d24b5953e70f48753fc3691790d278992a0c7'
$LOCK_COMMIT = 'ed16b69d027ae0080e96708b6a667727cbfd7137'
$UTF8 = New-Object System.Text.UTF8Encoding $false

function Log([hashtable]$h) {
    $h['utc'] = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    [IO.File]::AppendAllText($LOG, (($h | ConvertTo-Json -Compress -Depth 5) + "`n"), $UTF8)
}
function Py([string]$code) {
    $out = & $PY -c $code 2>&1
    return @{ rc = $LASTEXITCODE; out = (($out | ForEach-Object { "$_" }) -join ' ').Trim() }
}
function RunStage([string]$stage) {
    $so = Join-Path $OUT "phase_d_$stage.out.log"; $se = Join-Path $OUT "phase_d_$stage.err.log"
    $p = Start-Process -FilePath $PY -WorkingDirectory $WT -NoNewWindow -Wait -PassThru `
         -ArgumentList @('-u', '-m', 'research.event_response_map_v1.phase_d', '--go', '--eligibility-raw-approved', '--stage', $stage) `
         -RedirectStandardOutput $so -RedirectStandardError $se
    return $p.ExitCode
}
function MoveAside([string[]]$paths, [string]$tag) {
    $dst = Join-Path $OUT ("_{0}_{1}" -f $tag, (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
    New-Item -ItemType Directory -Force $dst | Out-Null
    foreach ($p in $paths) { if (Test-Path $p) { Move-Item $p $dst } }
    return $dst
}

New-Item -ItemType Directory -Force $OUT | Out-Null
Set-Location $WT
$env:PYTHONIOENCODING = 'utf-8'
$sha = (& $GIT rev-parse HEAD 2>$null)
$fp  = Py "import sys; sys.path.insert(0, '.'); from research.event_response_map_v1.fingerprint import fingerprint; print(fingerprint())"
Log @{ event = 'START'; mode = $(if ($PreflightOnly) { 'PREFLIGHT_ONLY' } else { 'PHASE_D' }); sha = $sha; fingerprint = $fp.out;
       user = [Security.Principal.WindowsIdentity]::GetCurrent().Name; host = $env:COMPUTERNAME; pid = $PID }

# ------------------------------------------------------------------------------------------------ preflight
$fail = @()
$checks = [ordered]@{}
$checks.venv_python = (Test-Path $PY);                       if (-not $checks.venv_python) { $fail += 'venv python not found' }
$checks.fingerprint_ok = ($fp.out -eq $EXPECT_FP);           if (-not $checks.fingerprint_ok) { $fail += "fingerprint mismatch: $($fp.out)" }
& $GIT merge-base --is-ancestor $LOCK_COMMIT HEAD 2>$null
$checks.lock_commit_is_ancestor = ($LASTEXITCODE -eq 0);     if (-not $checks.lock_commit_is_ancestor) { $fail += 'HEAD does not descend from the rev-3 lock commit' }
$dirty = @(& $GIT status --porcelain -- research tests docs 2>$null)
$checks.worktree_clean = ($dirty.Count -eq 0);               if (-not $checks.worktree_clean) { $fail += "worktree dirty: $($dirty -join '; ')" }
$envchk = Py "import sys; sys.path.insert(0, '.'); from research.event_response_map_v1.universe_source import headers; h = headers(); print('ENV_OK' if all(h.values()) else 'ENV_EMPTY')"
$checks.env_readable = ($envchk.out -eq 'ENV_OK');           if (-not $checks.env_readable) { $fail += "Alpaca keys not readable from .env: $($envchk.out)" }
$gchk = Py "import sys; sys.path.insert(0, '.'); from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard; LockedRangeGuard(EVENT_RESPONSE_MAP_V1); print('GUARD_OK')"
$checks.guard_state_ok = ($gchk.out -eq 'GUARD_OK');         if (-not $checks.guard_state_ok) { $fail += "guard: $($gchk.out)" }
$ny = Py "from datetime import datetime, timezone; from zoneinfo import ZoneInfo; t = datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')); print(('WEEKEND ' if t.weekday() >= 5 else 'WEEKDAY ') + t.isoformat())"
$checks.ny_time = $ny.out
$checks.ny_weekend = $ny.out.StartsWith('WEEKEND');          if (-not $checks.ny_weekend) { $fail += "not a New York weekend day ($($ny.out))" }
Log @{ event = 'PREFLIGHT'; checks = $checks }
if ($fail.Count -gt 0) { Log @{ event = 'ABORT'; reasons = $fail }; exit 2 }
if ($PreflightOnly)    { Log @{ event = 'END'; result = 'PREFLIGHT_ONLY_PASSED' }; exit 0 }

# ------------------------------------------------------------------------------------------------ download (D1)
$arch = Join-Path $OUT '_archive'
$rc = RunStage 'download'; Log @{ event = 'DOWNLOAD'; attempt = 1; rc = $rc }
if ($rc -ne 0) {
    $moved = MoveAside @((Join-Path $arch 'alpaca'), (Join-Path $arch 'alpaca_diag')) 'failed_download'
    Log @{ event = 'RESTART'; stage = 'download'; reason = "rc=$rc"; partial_archive_moved_to = $moved }
    $rc = RunStage 'download'; Log @{ event = 'DOWNLOAD'; attempt = 2; rc = $rc }
    if ($rc -ne 0) { Log @{ event = 'ABORT'; reasons = @("download failed twice (rc=$rc)") }; exit 4 }
}

# ------------------------------------------------------------------------------------------------ scoring (D2, once)
$outputs = @('trial_ledger.json', 'cells.csv', 'report.md', 'd0_coverage.json') | ForEach-Object { Join-Path $OUT $_ }
$crash = $null
$rc = RunStage 'run'; Log @{ event = 'RUN'; attempt = 1; rc = $rc }
$complete = (($outputs | Where-Object { -not (Test-Path $_) }).Count -eq 0)
if ($rc -ne 0 -and -not $complete) {
    $moved = MoveAside $outputs 'crashed_run'
    $crash = "scoring pass crashed (rc=$rc) before its outputs were complete; partial outputs moved to $moved; re-executed once"
    Log @{ event = 'CRASH'; stage = 'run'; rc = $rc; partial_outputs_moved_to = $moved }
    Log @{ event = 'RESTART'; stage = 'run' }
    $rc = RunStage 'run'; Log @{ event = 'RUN'; attempt = 2; rc = $rc }
    $complete = (($outputs | Where-Object { -not (Test-Path $_) }).Count -eq 0)
}
if (-not $complete) { Log @{ event = 'ABORT'; reasons = @("scoring outputs incomplete (rc=$rc)") }; exit 5 }
if ($crash) { [IO.File]::AppendAllText((Join-Path $OUT 'report.md'), "`n## Run history`n`n- $crash`n", $UTF8) }
$first = (Get-Content (Join-Path $OUT 'report.md') -TotalCount 1)
Log @{ event = 'END'; result = 'GATE_D_STOP'; run_rc = $rc; report_first_line = $first; crashed_and_restarted = [bool]$crash }
exit 0
