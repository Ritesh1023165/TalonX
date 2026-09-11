# Deployment candidate — controlled activation procedure (Task 117 §8)

**This procedure has NOT been executed.** It is the exact, supported sequence a
reviewer would run tomorrow after accepting the release. Nothing here launches
automatically.

Release SHA: see `MORNING_HANDOFF.md` (final Task 117 commit on
`research/talonx-strategy-validation`). V2 fingerprint `11107198c5b81237`
(frozen, unchanged). Frozen contract unchanged: ≥2 distinct code-P owners / 10 td
per issuer, next XNYS-session-open entry, 10-td hold,
`max_entry_staleness_sessions=3`, 5-td cooldown, equal-notional paper,
$300,000 campaign, membership-OR-liquidity eligibility.

## 0. Pre-flight (read-only)

```
git -C C:\workspace\TalonX rev-parse HEAD                 # == release SHA
python -m talonx_ops.prospective preflight --expected-sha <RELEASE_SHA>
python -m talonx_ops.prospective status
```
`preflight` checks SHA, .env vars, DB continuity, Redis reachability. Expect
`overall: READY`. If `NOT_READY`, stop and read `preflight.md`.

Confirm the `.env` carries the four `TALONX_V2*` vars (Task 112S S2) and the
Telegram credentials. Redis container `talonx-redis`, `run_id
50c35db7f72366789f96c6f1e3718e8942494176` — never flush / restart.

## 1. Back up mutable state (copy, never move)

```
copy %USERPROFILE%\.talonx\v2_lane.db            v2_lane.db.pre_activation_<UTC>
copy %USERPROFILE%\.talonx\ingestion_ledger.db  ingestion_ledger.db.pre_activation_<UTC>
copy %USERPROFILE%\.talonx\.env                 env.pre_activation_<UTC>
```
`v2_lane.db` is currently **absent** in `~/.talonx` (fresh Day-1). The ledger-
continuity guard (`talonx_ops/prospective`) fails closed and only ever *copies*
`v2_lane.db`, never resets it. No schema migration is required for this release
(the `intelligence_delivery` additive `ALTER TABLE` for `attempt_id` /
`in_flight_since_utc` / `transport_message_id` runs automatically and
idempotently on first `DeliveryOutbox` open; it is additive-only and reversible
by ignoring the new columns).

## 2. Start the V2 trading stack (atomic, single-writer)

```
python -m talonx_ops.prospective start ^
  --expected-sha <RELEASE_SHA> ^
  --tick-seconds 150 ^
  --heartbeat-seconds 30 ^
  --live-lookback-days 5 ^
  --pricing-mode composite-yf ^
  --execution-scope resolved-active-watchlist ^
  --deliver --transport telegram          # V2 TRADING-lane alerts only
```

- Acquires `SingleWriterLock(v2_lane.db)` **before** the process scan and any
  spawn. A second `start` while this one is live → `START REFUSED`
  (`REFUSED_ALREADY_RUNNING`, exit 3). `--force` does **not** break a live lock.
- Spawns exactly: `talonx_ops.supervisor run` + one `talonx_v2.run --mode live
  --form4-source insider` companion (never `supervisor include_v2` — Task 112T
  T1: that path reads stale parquet). `--deliver --transport telegram` is passed
  to the companion here so there is no second manual companion.
- The command then re-polls `verify_running` + the heartbeat file every 3 s for
  up to `GRACE_S = 120` s. This loop **is** the STARTING → READY/FAILED
  resolution mechanism.

### Readiness gate (verdict)
`READY` requires **all** of: `supervisor_alive`, `v2_companion_alive`,
`dashboard_8787`, **and** a fresh first-tick heartbeat (`age < 180 s`,
`strategy_version` present). Exit codes: `READY 0 · STARTING 0 · NOT_STARTED 2 ·
REFUSED 3 · FAILED_WITH_RESIDUALS 4`. On `FAILED_WITH_RESIDUALS` the command
runs an ownership-safe `stop_stack` and writes `start_cleanup.json`.

Confirm on `http://127.0.0.1:8787` → **Active V2**: fingerprint
`11107198c5b81237`, real capital BLOCKED, `$300,000` cash, first heartbeat
fresh; **Overview** runtime badges.

## 3. (Separately) activate Intelligence-card delivery

Intelligence-card delivery is **not** part of the `prospective start` stack — it
is the `talonx_ingest.intelligence.service` poll loop (its own supervised
process, Task 96B). The product decision to deliver eligible informational
Intelligence cards is already made.

### 3a. Drain the historical backlog on a copy (see `backlog_rehearsal.md`)
```
copy %USERPROFILE%\.talonx\ingestion_ledger.db  ledger.backlogcheck_<UTC>.db
python -c "from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox; \
ob=DeliveryOutbox(r'ledger.backlogcheck_<UTC>.db'); \
import datetime as d; \
print(len(ob.expire_stale(now=d.datetime.now(d.timezone.utc), max_age_seconds=None, \
event_time_lookup=None)))"
```
At any activation on/after 2026-09-12 this expires all 9,843 rows. Apply the
same `expire_stale` **once** to the live ledger while the poll loop is still in
`disabled` mode (EXPIRED is auditable: content kept, log line written, never
SENT, never deleted).

### 3b. Enable delivery
Config propagation — delivery goes `enabled` only when **all three** hold:
`deliver_intelligence_cards=True` **and** `dry_run_delivery=False` **and**
Telegram configured.

```
set TALONX_INTEL_DELIVER_CARDS=1
set TALONX_INTEL_DRY_RUN_DELIVERY=0
set TALONX_INTEL_DELIVER_PER_CYCLE=20
set TALONX_INTEL_DELIVER_TIMEOUT_SECONDS=20
set TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS=21600
set TALONX_INTEL_DELIVER_AGE_CUTOFF=1
python -m talonx_ingest.intelligence.service poll --duration 3600 \
    --send --i-understand-external-send
```
`--send` flips both enablement gates (env vars are the alternative path);
`--send` is refused without `--i-understand-external-send`. After the backlog
drain (3a) the first enabled cycle has 0–2 IMMEDIATE rows + at most one digest
message — it cannot flood Telegram (`process_pending` expires first, then caps
at `deliver_cards_per_cycle`; `process_digest` aggregates one message per 6 h
bucket with restart-safe dedup).

Verify on the dashboard: Intelligence → **Card delivery** (sent today, last card
sent, by-state); Paper/EOD → **Official Telegram — last confirmed send**.

## 4. End-of-day (OPERATOR-DRIVEN)

```
python -m talonx_ops.prospective close          # add --no-shutdown to keep the stack up
```
EOD reconciliation is **operator-driven**. The checkpoint daemon
(`session-loop`, spawned by `start` unless `--every 0`) runs 30-minute
CRITICAL-only checkpoints and `events.jsonl` — it does **not** run EOD
reconciliation and does not flatten positions. `prospective close`:
- writes `eod_session_report`, `lane_accounting_eod.json`
  (`build_lane_accounting`), reconciliation JSON;
- then performs an **ownership-safe** `stop_stack` (reaps only pid-tree members
  verified by create-time + cmdline; removes the startlock only when no residual
  remains) unless `--no-shutdown`.
No new recurring job is introduced by this release.

## 5. Rollback

See `rollback.md`. In short: `prospective close` → restore the
`*.pre_activation_<UTC>` copies → `git checkout <PREV_SHA>` → the additive
`intelligence_delivery` columns are inert if unused.

## Supported commands referenced (all real)

| command | purpose |
|---|---|
| `python -m talonx_ops.prospective preflight --expected-sha <SHA>` | read-only gate |
| `python -m talonx_ops.prospective start [flags above]` | atomic single-writer stack start + verdict |
| `python -m talonx_ops.prospective status` | current stack + verdict |
| `python -m talonx_ops.prospective close [--no-shutdown] [--force]` | EOD reconciliation + ownership-safe shutdown |
| `python -m talonx_ingest.intelligence.service poll --send --i-understand-external-send` | Intelligence-card delivery poll loop |
| `python dashboard_web.py --port 8787` | primary cockpit (started by the supervisor under `start`) |
