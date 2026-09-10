# TalonX — Operations

The one obvious path. The Task 100B supervisor owns start / health / restart / stop.

## Prospective V2 campaign day (Task 114 — the autonomous operator)

For a prospective **INSIDER_BUY_CLUSTER_V2@1** validation day, use the deterministic
autonomous operator instead of driving the supervisor by hand:

```powershell
# MORNING -- one command: preflight + start base stack + V2 companion + checkpoint daemon
python -m talonx_ops.prospective start

# DURING THE DAY -- nothing. Cockpit: http://localhost:8787 -> Overview -> Active V2.
#   machine-readable checkpoint every 30 min + events.jsonl in results\prospective_<date>\
#   quick read:  python -m talonx_ops.prospective status
#   only act on CRITICAL events (locked-invariant breach) -- fail safe, do not tune.

# EVENING -- one command: final checkpoint + reconciliation + report + graceful shutdown
python -m talonx_ops.prospective close
```

- **Ledger continuity (locked):** `C:\workspace\TalonX\v2_lane.db` is the authoritative
  carry-forward campaign ledger. The operator **never** resets, recreates, truncates or
  reseeds it. `start`/`close` fail **closed** on a ledger-integrity problem — genuine
  corruption is a manual restore from the newest `results\prospective_*\v2_lane.db.eod-copy`,
  never a fresh $300k ledger.
- **Heartbeat:** the V2 companion writes a lightweight health heartbeat every
  `--heartbeat-seconds` (default 30), decoupled from `--tick-seconds` (default 300, strategy
  evaluation only). A long strategy poll interval no longer makes the service look stale.
- **Healthy zero-activity is normal.** `service_health HEALTHY` + `data_state CURRENT` +
  `business_activity NO_OPPORTUNITIES` on a quiet day is a PASS, not a fault. A natural V2 BUY
  is not required for an operational PASS.
- **Open V2 position at close:** preserved OPEN in the ledger for its 10-trading-session hold.
  There is no EOD forced flatten.
- Full runbook: `results/task114_autonomous_operator/TASK115_OPERATOR_SHEET.md`.
- Release: `54c9b40` · V1 fp `2ae6216bca70` · V2 fp `11107198c5b81237`.

### V2 alert / paper / delivery path (Task 117 overnight — additive, frozen economics unchanged)

- **Pre-open entry intent.** When a cluster fires and its eligible entry session has not yet
  started, the companion persists a durable `pending_entry_intents` row in `v2_lane.db` and
  emits an **actionable** "PLANNED BUY at the OPEN of `<S>`" alert. On a later tick, once
  `<S>`'s bar is FINAL, the **unchanged** frozen pipeline fills at `<S>`'s open and links the
  fill to the intent (a delayed "BUY FILLED" notification). Cold-start with a backlog labels
  the fill "not prospectively actionable". Idempotent across ticks + restarts.
- **Durable alert delivery.** Every V2 alert is written to `v2_alert_outbox` (`event_id` PK →
  tick/restart dedup). `python -m talonx_v2.run --mode live --deliver` drains it each tick
  through `OfficialExternalRouter` (the one routing authority; per-family store dedup) into an
  injected transport. Default transport = **dry-run HOLD** (records intent, sends nothing).
  States are explicit: `SENT` / `HELD` / `RETRY` (bounded backoff) / `FAILED` / `AMBIGUOUS`.
  Experimental external delivery stays structurally blocked. No network transport is wired to
  run by this release.
- **Exit management is decoupled from source failure.** An unavailable SEC Form-4 source blocks
  **new** event-based entries/intents only; positions already OPEN still get due-exit
  evaluation on reliable bar prices → the established pending / fall-forward / `EXIT_UNRESOLVED`
  states. No forced liquidation at invented prices.
- **Dashboard.** `http://localhost:8787` has an **Active V2** tab: strategy/version/fingerprint;
  five independent signals (process / data / coverage / pricing / activity — an open position
  never masks degraded coverage/pricing); the $300k ledger; PENDING pre-open intents; the full
  funnel `Form 4 → clusters → decisions → paper → delivery`; and the alert-delivery table
  (a TRADING lane, separate from Intelligence & Experimental).
- **Coverage report:** `python -m talonx_ops.watchlist_coverage` — read-only per-ticker map of
  configured horizon → serving method, V2 scope, eligibility, paper ledger. Intraday and
  long-term have **no validated edge**; V2 is the only paper candidate.


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
