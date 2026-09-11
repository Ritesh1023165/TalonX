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

## 1. Resolve real paths and back up mutable state (copy, never move)

**Corrected from an earlier draft of this document, which wrongly assumed
`v2_lane.db` lived under `~/.talonx` and was absent ("fresh Day-1"). It is
neither.** The actual paths, traced from `talonx_ops/prospective/paths.py`
and `talonx_ingest/config.py`:

| store | actual path | resolved by |
|---|---|---|
| V2 campaign ledger | `<REPO_ROOT>\v2_lane.db` (repo root, e.g. `C:\workspace\TalonX\v2_lane.db`) | `talonx_ops.prospective.paths.V2_DB_PATH = REPO_ROOT / "v2_lane.db"` |
| V2 status file | `<REPO_ROOT>\v2_service_status.json` | `paths.V2_STATUS_PATH` |
| non-secret V2 env (4 vars) + secrets | `<REPO_ROOT>\.env` (gitignored) | `paths.resolve_env()` |
| SEC ingestion ledger (InsiderStore + Intelligence delivery outbox) | `%USERPROFILE%\.talonx\ingestion_ledger.db` | `TALONX_LEDGER_PATH` env, default in `talonx_ingest/config.py` |
| watchlist | `%USERPROFILE%\.talonx\watchlist.db` (legacy/Original home — **not** V2-specific) | `talonx_ops.watchlist_coverage` |

`v2_lane.db` is an **established campaign ledger, not absent** — verified
directly (md5 `29e57dbcd1a567fbc4bb0e73efdba95f`): `portfolio` cash
`$300,000.00`, 0 open positions, 0 trades, **one** `processed_episodes` row
(`07242bc857569f60` / ABCL / `SKIPPED_ENTRY_STALE`, from Task 113), 0 pending
entry intents, 0 alert-outbox rows. Do **not** treat it as a fresh ledger and
do **not** seed or recreate it if for some reason it is found missing — the
ledger-continuity guard (`talonx_ops/prospective/preflight.py`) already **fails
closed** in that case ("DO NOT recreate — carry-forward ledger is missing")
and this procedure follows the same rule: if `v2_lane.db` is unexpectedly
absent at activation time, **stop and investigate**, do not proceed.

```
copy <REPO_ROOT>\v2_lane.db               v2_lane.db.pre_activation_<UTC>
copy <REPO_ROOT>\v2_service_status.json   v2_service_status.json.pre_activation_<UTC>
copy <REPO_ROOT>\.env                     env.pre_activation_<UTC>          [KEEP OUTSIDE any tracked dir; contains secrets]
copy %USERPROFILE%\.talonx\ingestion_ledger.db  ingestion_ledger.db.pre_activation_<UTC>
```
Verify the backup before proceeding: `certutil -hashfile v2_lane.db.pre_activation_<UTC> MD5`
must equal the live file's hash. The `.env` backup contains Telegram/Alpaca
secrets — store it outside any git-tracked directory, and never print its
contents to a log or terminal that gets captured into evidence.

### Automatic schema changes (all additive, all verified safe on isolated copies)

| store | change | idempotent? |
|---|---|---|
| `ingestion_ledger.db` → `intelligence_delivery` | `ALTER TABLE ... ADD COLUMN attempt_id / in_flight_since_utc / transport_message_id` on first `DeliveryOutbox` open (checked against `PRAGMA table_info` first) | yes — only added if missing |
| `ingestion_ledger.db` | `CREATE TABLE IF NOT EXISTS` for `schema_meta`, `intelligence_delivery`, `intelligence_delivery_log`, `insider_filings`, `insider_transactions`, `insider_filing_evidence`, etc. | yes |
| `v2_lane.db` → `v2_alert_outbox` | `ALTER TABLE ... ADD COLUMN deliver_by_utc TEXT` (pre-existing, not from this task) | yes |
| `v2_lane.db` | `CREATE TABLE IF NOT EXISTS` for `processed_episodes`, `positions`, `trades`, `cooldowns`, `portfolio`, `pending_entry_intents`, `v2_alert_outbox` | yes |

None of these are "no migration" — opening the stores DOES perform
`ALTER`/`CREATE` statements every time. They are safe because they are
strictly additive and idempotent, not because nothing happens.

### Rehearsal on isolated copies (executed tonight, evidence below)

Real copies of the **live** `v2_lane.db` (md5 `29e57dbcd1a567fbc4bb0e73efdba95f`)
and `ingestion_ledger.db` were made to an isolated temp directory, then opened
through the real `V2Store` / `DeliveryOutbox` classes (the exact code path
`prospective start` / the Intelligence poll loop use) to trigger the additive
migrations for real, then re-snapshotted:

| field | before | after |
|---|---|---|
| `portfolio` cash | 300000.0 | 300000.0 (unchanged) |
| `positions` | 0 rows | 0 rows |
| `trades` | 0 | 0 |
| `processed_episodes` | 1 row: ABCL `SKIPPED_ENTRY_STALE` | same 1 row, byte-identical |
| `pending_entry_intents` | 0 rows | 0 rows |
| `v2_alert_outbox` | 0 rows | 0 rows |
| `intelligence_delivery` state counts | `{PENDING: 9843}` | `{PENDING: 9843}` (unchanged) |
| `intelligence_delivery` columns | 23 (no `attempt_id`/`in_flight_since_utc`/`transport_message_id`) | 26 (3 new columns added, all `NULL`) |

Cash, positions, the stale ABCL disposition, intents and delivery history all
survive backup + migration intact. The isolated copies were deleted after the
rehearsal (they contained a full copy of live campaign/ingestion data and were
never committed).

## 2. Start the V2 trading stack (atomic, single-writer)

```
python -m talonx_ops.prospective start ^
  --expected-sha <RELEASE_SHA> ^
  --tick-seconds 150 ^
  --heartbeat-seconds 30 ^
  --live-lookback-days 45 ^
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

## 3. Activate Intelligence-card delivery — the SAME supervised process, no second poller

**Corrected from an earlier draft, which described a separate, manually-run
`poll --send` process.** That would be a *second, unconfigured* Intelligence
poller racing the one the supervisor already starts. There is exactly **one**
Intelligence producer/drainer: the `intelligence` `ComponentSpec` in
`talonx_ops.supervisor.default_talonx_components()` — spawned automatically by
`talonx_ops.supervisor run`, which `prospective start` (step 2) already
launches. See `supervised_intelligence.md` for the full acceptance evidence.
The product decision to deliver eligible informational Intelligence cards is
already made.

### 3a. Drain the historical backlog on a copy (see `docs/audits/task117_final_activation_corrections/backlog_rehearsal.md`)

**`event_time_lookup=None` must NEVER be used** — that silently drops the
real event-acceptance-time basis the live runtime uses, so "unknown"
freshness could be judged more favourably than the real policy allows. Use
the same lookup shape `runner.py::deliver_cycle` uses (join
`text_events.accepted_at_utc`):
```
copy %USERPROFILE%\.talonx\ingestion_ledger.db  ledger.backlogcheck_<UTC>.db
python -c "
import sqlite3, datetime as d
from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
path = r'ledger.backlogcheck_<UTC>.db'
con = sqlite3.connect(path)
event_time = {}
for eid, acc in con.execute('SELECT event_id, accepted_at_utc FROM text_events WHERE accepted_at_utc IS NOT NULL'):
    try: event_time[eid] = d.datetime.fromisoformat(str(acc).replace('Z','+00:00'))
    except Exception: pass
con.close()
ob = DeliveryOutbox(path)
now = d.datetime.now(d.timezone.utc)   # the REAL activation instant -- never a placeholder date
expired = ob.expire_stale(now=now, max_age_seconds=None, event_time_lookup=event_time.get)
print(len(expired), 'expired at', now.isoformat())
ob.close()
"
```
Rehearsed at 2026-09-11T07:17:03Z: **9,840 EXPIRED, 3 still genuinely fresh**
(full detail in `backlog_rehearsal.md`) — recompute at the actual activation
instant, do not reuse this number. Apply the same `expire_stale` **once** to
the live ledger *before step 2* (i.e. before the supervised intelligence
component starts polling — auditable: content kept, log line written, never
SENT, never deleted).

### 3b. Enable delivery — set the env vars BEFORE `prospective start` (step 2)
Config propagation: `talonx_ops.supervisor.SubprocessRunner.spawn()` builds
every child's environment as `env = dict(os.environ)` — the supervisor
process's own environment (inherited from whatever launched it, i.e.
`prospective start`'s own environment) reaches the supervised `intelligence`
child unmodified. So these are exported **once, before step 2**, in the same
shell:
```
set TALONX_INTEL_DELIVER_CARDS=1
set TALONX_INTEL_DRY_RUN_DELIVERY=0
set TALONX_INTEL_DELIVER_PER_CYCLE=20
set TALONX_INTEL_DELIVER_TIMEOUT_SECONDS=20
set TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS=21600
set TALONX_INTEL_DELIVER_AGE_CUTOFF=1
```
Delivery goes `enabled` only when **all three** hold:
`deliver_intelligence_cards=True` **and** `dry_run_delivery=False` **and**
Telegram configured — verified directly (`test_task117_supervised_intelligence.py`)
by spawning a real child through the exact same `SubprocessRunner.spawn()`
path and confirming both env vars land in its environment unchanged. Missing
config is visible, not silently ON: with either var unset the supervised
child logs `mode=disabled` every cycle and the dashboard's Card-delivery block
stays at 0 SENT with an explicit note explaining why.

After the backlog drain (3a) the first enabled cycle has 0–2 IMMEDIATE rows +
at most one digest message — it cannot flood Telegram (`process_pending`
expires first, then caps at `deliver_cards_per_cycle`; `process_digest`
aggregates one message per 6 h bucket with restart-safe dedup).

Verify on the dashboard: Intelligence → **Card delivery** (sent today, last card
sent, by-state); Paper/EOD → **Official Telegram — last confirmed send**;
Overview → `intelligence` producer heartbeat (proves it is the ONE supervised
process, not a second manual one).

Canonical shutdown: `prospective close` (step 4) stops the supervisor, whose
owned-tree teardown (`_owned_tree`/`_terminate`, ownership-verified by
create-time + cmdline) reaps the supervised `intelligence` child along with
everything else — there is nothing separate to remember to stop.

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
