# Exact full-day launch procedure (DO NOT RUN until the verdict is FULL_DAY_GO and PR #13 is merged to main)

```powershell
cd C:\workspace\TalonX
git fetch origin
git checkout main
git pull --ff-only origin main            # must include the PR #13 merge commit
git rev-parse v2-paper-rc1^{commit}        # a56ec8c8d10adb36a113ebd373204f297c230081

$env:TALONX_V2_CAMPAIGN_ID='V2-PAPER-RC1'
$env:TALONX_V2_DB_PATH='v2_release_rc1.db'
$env:TALONX_V2_STATUS_PATH='v2_release_rc1_status.json'
$env:TALONX_V2_STARTING_CASH_USD='100000'
$env:TALONX_V2_ALLOCATION_USD='10000'
$env:TALONX_V2_EXECUTION_MODE='PAPER'
$env:TALONX_NOTIFY_DB_PATH='v2_release_rc1_notifications.db'

.venv\Scripts\python.exe -m talonx_v2.release_gate --verify-campaign     # NEVER --init-campaign again
.venv\Scripts\python.exe -m talonx_v2.release_gate                       # must be READY (0 FAIL)

.venv\Scripts\python.exe -m talonx_ops.prospective start --release --expected-sha a56ec8c --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 --execution-scope resolved-active-watchlist --deliver --transport telegram
```
