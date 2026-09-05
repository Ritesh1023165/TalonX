# TalonX — Operations

The one obvious path. The Task 100B supervisor owns start / health / restart / stop.

## Prerequisites

- Python 3.11/3.12 in `.venv` (`.venv/Scripts/python.exe` on Windows).
- Redis up: `docker compose up -d` (`docker-compose.yaml` → `talonx-redis` on `:6379`).
- `.env` at the repo root (copy `.env.example`); at minimum set `TALONX_SEC_USER_AGENT`.

## START

```powershell
.\scripts\start_talonx_supervised.ps1
#   = python -m talonx_ops.supervisor run
#   launches, under one supervision model:
#     Original CONTROL      run_talonx.py                                   (MANDATORY)
#     Experimental shadow   python -m talonx_signals.run                    (OPTIONAL)
#     Intelligence service  ... intelligence.service poll --with-backfill   (OPTIONAL)
#     :8787 cockpit         dashboard_web.py                                (OPTIONAL)
#   Ctrl+C = controlled shutdown (10-step order) + EOD reconciliation persist.
```

Bounded run (for the pending Task 103 live qualification):
`python -m talonx_ops.supervisor run --tick 15 --max-ticks 240` — ~60 min, then self-stops and
runs the controlled shutdown.

## STATUS

```powershell
python -m talonx_ops.supervisor status
```

The `answers` block answers, from one command: `talonx_running` · `original_ready` ·
`market_feed_healthy` (+ `market_feed_state`) · `experimental_shadow_alive` ·
`intelligence_alive` · `telegram_send_ok` · `telegram_receive_owner_count` ·
`original_open_positions` · `experimental_open_positions` · `eod_reconciled_today` ·
`dashboard_url` (http://localhost:8787) · `intelligence_deep_viewer` (http://localhost:8760).

## DASHBOARD

- Primary cockpit: **http://localhost:8787** — see `docs/DASHBOARD.md`.
- Local admin: **http://localhost:8787/admin/** — see `docs/ADMIN.md`.
- Intelligence deep evidence: **http://localhost:8760**.

## STOP

```powershell
# supervised:  Ctrl+C in the supervisor console  -> controlled shutdown
# legacy:
.\scripts\stop_talonx.ps1
.\scripts\stop_dashboard_web.ps1
```

Controlled shutdown order (Task 99L contract): stop new external alert work → stop Telegram
receive → stop Experimental generation → flush forward telemetry → stop/flush Intelligence →
reconcile paper → persist EOD → stop Original consumers → stop market feed last → verify children
exited.

## EOD

`~/.talonx/eod_reconciliation.db` gets one row per session on controlled shutdown. Read it via
`supervisor status` (`eod_latest` / `eod_reconciled_today`) or the `:8787` **Paper / EOD**
section. Read-only broker checks only; PIV shows `NOT_CHECKED` unless an explicit reader is
injected. Idempotent per session date.

## Which script is authoritative?

| script | role |
|---|---|
| `scripts/start_talonx_supervised.ps1` | **PRIMARY** — start everything under the supervisor |
| `scripts/start_talonx.ps1` | **LEGACY / COMPATIBILITY** — `run_talonx.py` + Streamlit `:8501` only; also the target of `register_scheduled_tasks.ps1`'s 10am task |
| `scripts/start_dashboard_web.ps1` | `:8787` only, if you want the cockpit without the supervisor |
| `scripts/stop_talonx.ps1` / `stop_dashboard_web.ps1` | legacy stop helpers |
| `scripts/register_scheduled_tasks.ps1` | schedules the LEGACY path (unchanged) |
| `python -m talonx_signals.run` | Experimental lane + its embedded `:8770` telemetry dashboard — `[COMPATIBILITY]` |
| `python -m talonx_piv.cli` | opt-in Alpaca PAPER validation harness (see `docs/COMPATIBILITY.md`) |

## Live qualification (pending)

Task 103 (one 45-60 min real-RTH operational qualification) is **not yet run** — it was blocked
by a closed market. Re-run on a real US trading day (next open a weekday 13:30 UTC) via the
bounded supervisor command above. Nothing about the architecture needs to change first. See
`results/task103_live_qualification/` and `results/task102_operational_finalization/post_task100_live_verification.md`.
