# ERM nominee -- one-off launcher for the single locked historical validation, window B (owner GO 2026-10-06).
# Runs the LOCKED command unchanged:  python -m research.erm_nominee_validation.run --window B --execute
# Preconditions (each failure exits WITHOUT starting the run, so no acquisition attempt is consumed):
#   1. never launched before (exclusive LAUNCHED.lock)          -> no duplicate / competing launcher
#   2. UTC now in [2026-10-06T20:30Z, 2026-10-06T23:30Z)       -> R5 off-hours AND the runner pins R = UTC date = 2026-10-06
#   3. lock verifier PASS                                      -> protocol / implementation / config unchanged
$ErrorActionPreference = 'Stop'
$root = 'C:\workspace\TalonX-erm-val'
$py = 'C:\workspace\TalonX\.venv\Scripts\python.exe'
$out = Join-Path $root 'results\erm_nominee_validation\go_B'
$log = Join-Path $out 'launcher.log'
function L([string]$m) { Add-Content -Path $log -Value ("{0} {1}" -f [DateTime]::UtcNow.ToString('o'), $m) -Encoding UTF8 }

$lockPath = Join-Path $out 'LAUNCHED.lock'
try { $fs = [System.IO.File]::Open($lockPath, 'CreateNew', 'Write'); $fs.Close() }
catch { L 'REFUSED: LAUNCHED.lock exists (already launched); not starting'; exit 4 }

$now = [DateTime]::UtcNow
$lo = [DateTime]::SpecifyKind([DateTime]'2026-10-06T20:30:00', 'Utc')
$hi = [DateTime]::SpecifyKind([DateTime]'2026-10-06T23:30:00', 'Utc')
if ($now -lt $lo -or $now -ge $hi) { L ("REFUSED: UTC now {0} outside [{1}, {2}); not starting (nothing consumed)" -f $now.ToString('o'), $lo.ToString('o'), $hi.ToString('o')); exit 3 }

Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
L 'precheck: lock verify'
& cmd /c "`"$py`" -m research.erm_nominee_validation.lock verify > `"$out\lock_verify_prerun.json`" 2>&1"
if ($LASTEXITCODE -ne 0) { L "REFUSED: lock verify failed (exit $LASTEXITCODE); not starting"; exit 5 }

L 'START: python -u -m research.erm_nominee_validation.run --window B --execute'
& cmd /c "`"$py`" -u -m research.erm_nominee_validation.run --window B --execute > `"$out\run.out.log`" 2> `"$out\run.err.log`""
$rc = $LASTEXITCODE
L "END: exit $rc"
exit $rc
