# EVENT_RESPONSE_MAP_V1 Phase D runner (Windows Task Scheduler, S4U). NOT part of the design-lock fingerprint.
#   powershell -NoProfile -ExecutionPolicy Bypass -File run_phase_d.ps1 [-PreflightOnly] [-ScoringOnly]
# Writes one JSON line per step to results\event_response_map_v1\phase_d_runner.log:
#   START (utc, sha, fingerprint) -> PREFLIGHT -> [DOWNLOAD/RUN/CRASH/RESTART] -> END | ABORT
# Restart policy (documented in docs/research/preregistration/event_response_map_v1_nomination.md):
#   * the locked downloader is not symbol-resumable, so a failed download is retried ONCE from scratch (partial
#     archive moved aside; the SEC cache is reused by design);
#   * LOCK REV 3.1: a scoring pass that crashed before the one-shot marker (trial_ledger.json, written last) is
#     re-run ONCE, recorded in this log and appended to report.md; once the marker exists it is never re-run.
# SCORING-ONLY mode (-ScoringOnly; lock rev 3.2, the ONE allowed re-execution after attempt 1):
#   * NO download: the archived bytes are verified first (every file re-hashed; both aggregates must equal the pinned
#     values AND the guard audit log's download_manifest records) -- tools/verify_archive.py;
#   * NO network: the scoring process runs with research/event_response_map_v1/offline on PYTHONPATH, whose
#     sitecustomize refuses every socket connect / DNS lookup and fails loudly; a probe proves the refusal before the
#     run and the run's stderr must carry OFFLINE_GUARD_ACTIVE afterwards. This replaces the New-York-weekend check
#     (which exists only to keep live-shared Alpaca/SEC traffic off trading days) in this mode only;
#   * NO automatic crash re-run: this run IS the one re-execution; a crash is logged (CRASH + ABORT), owner decides.
# The runner never pushes to git and never touches the live worktree.
param([switch]$PreflightOnly, [switch]$ScoringOnly)
$ErrorActionPreference = 'Stop'
$WT   = 'C:\workspace\TalonX-erm'
$PY   = 'C:\workspace\TalonX\.venv\Scripts\python.exe'
$GIT  = 'C:\Program Files\Git\cmd\git.exe'
$OUT  = Join-Path $WT 'results\event_response_map_v1'
$LOG  = Join-Path $OUT 'phase_d_runner.log'
$EXPECT_FP   = '12a909e795986ff3abeac9ca92906a64c3387a5e3c64734f2b72031b781cb8ad'
$LOCK_COMMIT = '7ad102a76351b8bbf9c9a8b32bf32fdd14341132'
$ARCHIVE_MAIN_AGG = '4f6aa4c19184afe48fd2713b20e2e28a64773434dcd86decfad183d30c449587'   # guard audit 2026-10-03T14:35:58Z
$ARCHIVE_DIAG_AGG = '6a9e6f121cd321bb7c8dad2bfca8e8650e9c55efd4ede8db365cc36c90c7018d'   # guard audit 2026-10-03T14:39:23Z
$OFFLINE = Join-Path $WT 'research\event_response_map_v1\offline'
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
    if ($ScoringOnly) { $env:PYTHONPATH = $OFFLINE } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
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
$mode = $(if ($ScoringOnly) { 'SCORING_ONLY' } elseif ($PreflightOnly) { 'PREFLIGHT_ONLY' } else { 'PHASE_D' })
if ($ScoringOnly -and $PreflightOnly) { $mode = 'SCORING_ONLY_PREFLIGHT' }
Log @{ event = 'START'; mode = $mode; sha = $sha; fingerprint = $fp.out;
       user = [Security.Principal.WindowsIdentity]::GetCurrent().Name; host = $env:COMPUTERNAME; pid = $PID }

# ------------------------------------------------------------------------------------------------ preflight
$fail = @()
$checks = [ordered]@{}
$checks.venv_python = (Test-Path $PY);                       if (-not $checks.venv_python) { $fail += 'venv python not found' }
$checks.fingerprint_ok = ($fp.out -eq $EXPECT_FP);           if (-not $checks.fingerprint_ok) { $fail += "fingerprint mismatch: $($fp.out)" }
& $GIT merge-base --is-ancestor $LOCK_COMMIT HEAD 2>$null
$checks.lock_commit_is_ancestor = ($LASTEXITCODE -eq 0);     if (-not $checks.lock_commit_is_ancestor) { $fail += 'HEAD does not descend from the lock commit' }
$dirty = @(& $GIT status --porcelain -- research tests docs 2>$null)
$checks.worktree_clean = ($dirty.Count -eq 0);               if (-not $checks.worktree_clean) { $fail += "worktree dirty: $($dirty -join '; ')" }
if (-not $ScoringOnly) {
    $envchk = Py "import sys; sys.path.insert(0, '.'); from research.event_response_map_v1.universe_source import headers; h = headers(); print('ENV_OK' if all(h.values()) else 'ENV_EMPTY')"
    $checks.env_readable = ($envchk.out -eq 'ENV_OK');       if (-not $checks.env_readable) { $fail += "Alpaca keys not readable from .env: $($envchk.out)" }
}
$gchk = Py "import sys; sys.path.insert(0, '.'); from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard; LockedRangeGuard(EVENT_RESPONSE_MAP_V1); print('GUARD_OK')"
$checks.guard_state_ok = ($gchk.out -eq 'GUARD_OK');         if (-not $checks.guard_state_ok) { $fail += "guard: $($gchk.out)" }
if ($ScoringOnly) {
    # (a) archived bytes == the guard-audited download (every file re-hashed)
    $av = & $PY (Join-Path $WT 'research\event_response_map_v1\tools\verify_archive.py') $ARCHIVE_MAIN_AGG $ARCHIVE_DIAG_AGG 2>&1
    $checks.archive_verified = ($LASTEXITCODE -eq 0);         if (-not $checks.archive_verified) { $fail += "archive verification failed: $(($av | Out-String).Trim())" }
    $checks.archive_detail = (($av | Out-String).Trim())
    # (b) no network: the offline guard must refuse a real connection attempt
    $env:PYTHONPATH = $OFFLINE
    $nn = Py "import socket`ntry:`n    socket.create_connection(('data.sec.gov', 443), 5); print('NETWORK_REACHED')`nexcept RuntimeError as e:`n    print('REFUSED' if 'NETWORK_REFUSED_SCORING_ONLY' in str(e) else 'OTHER:' + str(e))"
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $checks.no_network_enforced = ($nn.out -match 'REFUSED$');  if (-not $checks.no_network_enforced) { $fail += "offline guard not effective: $($nn.out)" }
    # (c) a clean slate: no marker and no outputs from any earlier attempt
    $left = @('trial_ledger.json', 'cells.csv', 'report.md', 'd0_coverage.json') | Where-Object { Test-Path (Join-Path $OUT $_) }
    $checks.no_prior_outputs = ($left.Count -eq 0);           if (-not $checks.no_prior_outputs) { $fail += "outputs already present: $($left -join ', ')" }
} else {
    $ny = Py "from datetime import datetime, timezone; from zoneinfo import ZoneInfo; t = datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')); print(('WEEKEND ' if t.weekday() >= 5 else 'WEEKDAY ') + t.isoformat())"
    $checks.ny_time = $ny.out
    $checks.ny_weekend = $ny.out.StartsWith('WEEKEND');      if (-not $checks.ny_weekend) { $fail += "not a New York weekend day ($($ny.out))" }
}
Log @{ event = 'PREFLIGHT'; checks = $checks }
if ($fail.Count -gt 0) { Log @{ event = 'ABORT'; reasons = $fail }; exit 2 }
if ($PreflightOnly)    { Log @{ event = 'END'; result = 'PREFLIGHT_ONLY_PASSED' }; exit 0 }

# ------------------------------------------------------------------------------------------------ download (D1)
$arch = Join-Path $OUT '_archive'
if ($ScoringOnly) { Log @{ event = 'DOWNLOAD'; skipped = $true; reason = 'scoring-only: archive verified, no network' } }
$rc = $(if ($ScoringOnly) { 0 } else { RunStage 'download' })
if (-not $ScoringOnly) { Log @{ event = 'DOWNLOAD'; attempt = 1; rc = $rc } }
if ($rc -ne 0) {
    $moved = MoveAside @((Join-Path $arch 'alpaca'), (Join-Path $arch 'alpaca_diag')) 'failed_download'
    Log @{ event = 'RESTART'; stage = 'download'; reason = "rc=$rc"; partial_archive_moved_to = $moved }
    $rc = RunStage 'download'; Log @{ event = 'DOWNLOAD'; attempt = 2; rc = $rc }
    if ($rc -ne 0) { Log @{ event = 'ABORT'; reasons = @("download failed twice (rc=$rc)") }; exit 4 }
}

# ------------------------------------------------------------------------------------------------ scoring (D2, once)
# LOCK REV 3.1: phase_d writes the one-shot marker trial_ledger.json LAST. Rule: after a failed pass, if the marker is
# ABSENT the pass crashed before its outputs were complete -> log the crash and re-run ONCE (the re-run overwrites the
# partial outputs); if the marker is PRESENT never re-run.
$marker = Join-Path $OUT 'trial_ledger.json'
$crash = $null
$rc = RunStage 'run'; Log @{ event = 'RUN'; attempt = 1; rc = $rc; marker_present = (Test-Path $marker) }
if ($ScoringOnly) {
    $guardSeen = Select-String -Path (Join-Path $OUT 'phase_d_run.err.log') -Pattern 'OFFLINE_GUARD_ACTIVE' -Quiet
    Log @{ event = 'OFFLINE_GUARD'; active_in_run = [bool]$guardSeen }
    if ($rc -ne 0 -and -not (Test-Path $marker)) {
        Log @{ event = 'CRASH'; stage = 'run'; rc = $rc; marker_present = $false; note = 'scoring-only = the one re-execution; no automatic re-run' }
        Log @{ event = 'ABORT'; reasons = @("scoring-only run failed (rc=$rc); owner decides") }; exit 6
    }
}
if ($rc -ne 0 -and -not $ScoringOnly) {
    if (Test-Path $marker) {
        Log @{ event = 'RUN_FAILED_AFTER_MARKER'; rc = $rc; action = 'no re-run (marker present)' }
    } else {
        $crash = "scoring pass crashed (rc=$rc) before the one-shot marker was written; re-run once (partial outputs overwritten)"
        Log @{ event = 'CRASH'; stage = 'run'; rc = $rc; marker_present = $false }
        Log @{ event = 'RESTART'; stage = 'run' }
        $rc = RunStage 'run'; Log @{ event = 'RUN'; attempt = 2; rc = $rc; marker_present = (Test-Path $marker) }
    }
}
if (-not (Test-Path $marker)) { Log @{ event = 'ABORT'; reasons = @("scoring pass did not complete (no marker, rc=$rc)") }; exit 5 }
if ($crash) { [IO.File]::AppendAllText((Join-Path $OUT 'report.md'), "`n## Run history`n`n- $crash`n", $UTF8) }
$first = (Get-Content (Join-Path $OUT 'report.md') -TotalCount 1)
Log @{ event = 'END'; result = 'GATE_D_STOP'; run_rc = $rc; report_first_line = $first; crashed_and_restarted = [bool]$crash }
exit 0
