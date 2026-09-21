# Exact launch procedure (DO NOT RUN in this task)
```powershell
cd C:\workspace\TalonX
git fetch origin
git checkout main
git pull --ff-only origin main
$env:TALONX_V2_CAMPAIGN_ID='V2-PAPER-RC1'
$env:TALONX_V2_DB_PATH='v2_release_rc1.db'
$env:TALONX_V2_STATUS_PATH='v2_release_rc1_status.json'
$env:TALONX_V2_STARTING_CASH_USD='100000'
$env:TALONX_V2_ALLOCATION_USD='10000'
$env:TALONX_V2_EXECUTION_MODE='PAPER'
$env:TALONX_NOTIFY_DB_PATH='v2_release_rc1_notifications.db'
.venv\Scripts\python.exe -m talonx_v2.release_gate --verify-campaign
.venv\Scripts\python.exe -m talonx_v2.release_gate
.venv\Scripts\python.exe -m talonx_ops.prospective start --release --expected-sha a56ec8c --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 --execution-scope resolved-active-watchlist --deliver --transport telegram
```
Prerequisite: the refreshed Telegram validation record must be on main (PR #14) or present in the working tree, otherwise `signal_/sentinel_delivery_validation_bound` FAIL and `start --release` refuses. If PR #14 is merged while the local working copy
still carries the same record, run `git restore docs/research/evidence/v2_release_integration_ri4/delivery_validation.json` before `git pull --ff-only`.
