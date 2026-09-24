# Runbook: Continuous Opportunity Engine (research lane)

`python -m talonx_opportunity`. Requirements S14-01..S14-06. Architecture: `talonx_opportunity/__init__.py`.

The research lane **never trades**, never emits a V2 `TRADE_EVENT`, never writes a V2 ledger or outbox, and never imports `talonx_v2`. V2 runs exactly as before (`prospective start --release ...`), in its own window.

## What runs

Each component is its own OS process. Each has its own lock, heartbeat, stop flag and single-writer store under `results/opportunity/`.

| Logical component | `component` name | Writes | Cadence |
|---|---|---|---|
| DATA_INGESTION | `ingestion` | `market.db` (window-to-date aggregates, daily history, per-phase probes) | 60 s in a usable phase, 300 s otherwise |
| DISCOVERY | `discovery` | `opportunity.db` (**uncapped** candidates + lifecycle events + scans) | PREMARKET = V1 cadence (15 min / 5 min); REGULAR and AFTER_HOURS = 5 min |
| INTRADAY / SAME_DAY / SHORT_TERM / LONG_TERM evaluators | `evaluator:<H>` | `evaluator_<h>.db` | 30 s (LONG_TERM is registered, NOT_IMPLEMENTED) |
| NOTIFICATION_WORKER | `notifier` | `notification.db`, `opportunity_research_notifications.db` | 15 s |
| OUTCOME_TRACKING | `outcomes` | `outcomes.db` (evaluation only) | 10 min |
| REPORTING | `reporting` | `reports/<window>/session_report.{json,md}` | 15 min |
| PAPER_EXECUTION | (frozen V2 companion) | V2's own ledger | V2 schedule, observed read-only |

`runtime.db` holds component heartbeats, events and **deployment boundaries**.

## Provider capability per phase

Demonstrated on this subscription, 2026-09-24.

| Phase (ET) | Discovery | Why |
|---|---|---|
| PREMARKET 04:00–09:30 | runs | Alpaca SIP 1-min, 15-min delayed, consolidated |
| REGULAR | runs | same |
| AFTER_HOURS close–20:00 | runs | same |
| OVERNIGHT 20:00–04:00 | **fails closed** (`DATA_UNAVAILABLE`) | SIP has no overnight bars. BOATS is single-venue and sparse, so it is recorded but **disabled**, never mixed with SIP. |
| CLOSED (weekend / holiday) | idle | no session |

A failed live probe marks only that phase `UNAVAILABLE`. Every other component keeps running.

## Start (research window; never the V2 window)

```powershell
cd C:\workspace\TalonX
.venv\Scripts\python.exe -m talonx_premarket universe        # optional: refresh the broad universe (auto-refreshes after 30 h)
.venv\Scripts\python.exe -m talonx_opportunity up --supervise
```

- Record-only by default. The notifier records every decision and sends nothing.
- `--supervise` restarts **only** a component that died. Ctrl+C stops the supervisor; the components keep running.

**Lab delivery** is a double opt-in, set in this process's environment only:

```powershell
$env:TALONX_NOTIFY_RESEARCH_ENABLED = "1"          # never in .env, never in the V2 window
.venv\Scripts\python.exe -m talonx_opportunity up --deliver --supervise
```

`up --deliver` prints `LAB DELIVERY: deliver_flag=true research_destination_enabled=<bool>`. If it says `False`, alerts are enqueued but never sent.

## Operate

```powershell
.venv\Scripts\python.exe -m talonx_opportunity status            # SYSTEM / COMPONENTS / DATA / DISCOVERY / HORIZONS / NOTIFY / REPORT / PAPER
.venv\Scripts\python.exe -m talonx_opportunity capabilities
.venv\Scripts\python.exe -m talonx_opportunity restart notifier  # only the notifier; ingestion and discovery keep running
.venv\Scripts\python.exe -m talonx_opportunity stop discovery
.venv\Scripts\python.exe -m talonx_opportunity down              # stop all components gracefully
```

The same view appears on the `:8787` **Opportunity Engine** tab and on `/ping`.

## Live hot-fix procedure (deployment boundaries)

1. Change the code or config on a branch and review it.
2. **Declare** the change for the component you will restart, before restarting it:

   ```powershell
   .venv\Scripts\python.exe -m talonx_opportunity declare-change notifier --class ROUTING_FIX --reason "fix Lab render of MATERIAL_UPDATE"
   ```

   Classes: `OPERATIONS_ONLY`, `DATA_FIX`, `ROUTING_FIX`, `UI_ONLY`, `STRATEGY_MATERIAL`, `EXECUTION_MATERIAL`, `REPORTING_ONLY`.
3. `restart <component>`. The component records a deployment boundary at start, with its old and new version, commit, config fingerprints, classification and `affects_*` flags.
   - A pure restart (nothing changed) is `OPERATIONS_ONLY`, and comparability is intact.
   - A **config fingerprint change is always its material class** and cannot be declared down.
   - An undeclared code change gets the component's conservative default. For discovery and the evaluators that default is `STRATEGY_MATERIAL`.
4. Check `deployments`:

   ```powershell
   .venv\Scripts\python.exe -m talonx_opportunity deployments
   ```

   The EOD report then segments statistics at every material boundary and lists operations-only restarts as "comparability intact".

## End of day

```powershell
.venv\Scripts\python.exe -m talonx_opportunity report --window 2026-09-25
```

The report is written to `results/opportunity/reports/<window>/session_report.md`. It contains:

- deployment boundaries;
- comparability per metric family (candidates / outcomes / alerts / paper): aggregatable or SEGMENTED;
- per-segment candidates by first-seen phase;
- outcome statuses, +30m / close / MFE / MAE statistics;
- notification decisions and real delivery states (ENQUEUED is not SENT);
- horizon records (BUY/SELL count must be 0);
- read-only V2 identity.

It makes no profitability claim.

## Safety invariants (tested)

- Detection and persistence never depend on Telegram. A budget, Lab being disabled, or a notifier crash cannot drop a candidate.
- The budget (`LAB_NOTIFY_POLICY_V1`):
  - 25 new surfacings per trading window (V1's figure, kept for comparison);
  - WATCH is capped at 15 and 10 are reserved for BULLISH/BEARISH;
  - updates and invalidations are sent only for candidates already surfaced.
- Frozen V1 scoring (`PREMARKET_RESEARCH_V1` `62ba413daf85e674`) is embedded unchanged in `CONTINUOUS_RESEARCH_V1`. PREMARKET classification is identical to V1.
- `talonx_opportunity` refuses to open `v2_release_rc1*.db`, `v2_lane.db` and `notifications.db`.
