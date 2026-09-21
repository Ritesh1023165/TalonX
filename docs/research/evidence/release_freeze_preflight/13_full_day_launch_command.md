# Exact full-day launch procedure (DO NOT RUN in the freeze task)

Run from the repository root in ONE PowerShell window (the same window is used later for `close`/`checkpoint`/`status`).
Run before the XNYS open (13:30 UTC in September). Nothing here is executed by the freeze task.

```powershell
cd C:\workspace\TalonX
git fetch origin
git checkout main
git pull --ff-only origin main
git tag -v v2-paper-rc1 2>$null; git rev-parse v2-paper-rc1^{commit}     # must print a56ec8c8d10adb36a113ebd373204f297c230081

# 1) release campaign environment (non-secret; prints the same block: .venv\Scripts\python.exe -m talonx_v2.release_gate --print-env)
$env:TALONX_V2_CAMPAIGN_ID='V2-PAPER-RC1'; $env:TALONX_V2_DB_PATH='v2_release_rc1.db'; $env:TALONX_V2_STATUS_PATH='v2_release_rc1_status.json'
$env:TALONX_V2_STARTING_CASH_USD='100000'; $env:TALONX_V2_ALLOCATION_USD='10000'; $env:TALONX_V2_EXECUTION_MODE='PAPER'

# 2) ONE-TIME campaign creation (creates ONLY v2_release_rc1.db; refuses if it exists or if pointed at v2_lane.db)
.venv\Scripts\python.exe -m talonx_v2.release_gate --init-campaign

# 3) read-only readiness (expect status READY, all PASS; sends nothing)
.venv\Scripts\python.exe -m talonx_v2.release_gate

# 4) LAUNCH (the only command that starts the stack)
.venv\Scripts\python.exe -m talonx_ops.prospective start --release --expected-sha a56ec8c --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 --execution-scope resolved-active-watchlist --deliver --transport telegram
```

`start --release` re-runs the release gate itself, forces SIP (`V2_RELEASE_PRICE_CONTRACT@1`), requires `--deliver --transport telegram`, and exits 2 if anything is NOT_READY
(it writes `results/prospective_<date>/release_gate.json`). `--force` never bypasses the gate. Do NOT add `--pricing-mode csv`, `--enable-broad-discovery` or Lab flags.
If the campaign was already created on a previous day, skip step 2 (a campaign is created exactly once) and use `--verify-campaign` only on day 0.
