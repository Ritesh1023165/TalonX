# Deployment candidate — controlled activation procedure

**Corrected procedure order (Task 117 final activation, 2026-09-11):**
preflight → backups → isolated backlog check → additive migration + approved
expiry on production → delivery configuration → startup → acceptance → EOD →
rollback. An earlier draft numbered "start the stack" (now step 5) *before*
"activate delivery" (now step 4) while that same section's own text said its
env vars must be set *before* `prospective start` — an internal
contradiction. Fixed by reordering, not by rewording around it.

Release SHA: recorded in the session's evidence bundle at execution time. V2
fingerprint `11107198c5b81237` (frozen, unchanged). Frozen contract
unchanged: ≥2 distinct code-P owners / 10 td per issuer, next
XNYS-session-open entry, 10-td hold, `max_entry_staleness_sessions=3`, 5-td
cooldown, equal-notional paper, $300,000 campaign, membership-OR-liquidity
eligibility.

## 0. Pre-flight (read-only)

```
git -C C:\workspace\TalonX rev-parse HEAD                 # == release SHA
python -m talonx_ops.prospective preflight --expected-sha <RELEASE_SHA>
python -m talonx_ops.prospective status
```
`preflight` checks SHA, tree cleanliness, V1/V2 fingerprints, Redis
reachability, no stale processes, required ports free, V2 ledger continuity
(never recreated), V2 env vars resolved, active profile is V2, real capital
off, Experimental external override absent, heartbeat decoupled from tick,
Experimental external boundary blocked, Telegram logical owner, dashboard V2
section present. Expect **all `[OK]`, overall READY**. If any gate fails,
stop.

Confirm the `.env` carries the four `TALONX_V2*` vars (Task 112S S2) and the
Telegram credentials — check key **names** only, never print values. Redis
container `talonx-redis` — never flush / restart.

## 1. Resolve real paths and back up mutable state (copy, never move)

The actual paths, traced from `talonx_ops/prospective/paths.py` and
`talonx_ingest/config.py`:

| store | actual path | resolved by |
|---|---|---|
| V2 campaign ledger | `<REPO_ROOT>\v2_lane.db` (repo root, e.g. `C:\workspace\TalonX\v2_lane.db`) | `talonx_ops.prospective.paths.V2_DB_PATH = REPO_ROOT / "v2_lane.db"` |
| V2 status file | `<REPO_ROOT>\v2_service_status.json` | `paths.V2_STATUS_PATH` |
| non-secret V2 env (4 vars) + secrets | `<REPO_ROOT>\.env` (gitignored) | `paths.resolve_env()` |
| SEC ingestion ledger (InsiderStore + Intelligence delivery outbox) | `%USERPROFILE%\.talonx\ingestion_ledger.db` | `TALONX_LEDGER_PATH` env, default in `talonx_ingest/config.py` |
| watchlist | `%USERPROFILE%\.talonx\watchlist.db` (legacy/Original home — **not** V2-specific) | `talonx_ops.watchlist_coverage` |

`v2_lane.db` is an **established campaign ledger**, carried forward since
Task 113 — do **not** treat it as fresh and do **not** seed or recreate it if
it is ever unexpectedly missing (the ledger-continuity guard in
`talonx_ops/prospective/preflight.py` already fails closed on that case; this
procedure follows the same rule — stop and investigate).

**With no owned writer running** (verify via `prospective status` /
`preflight`'s `no_stale_talonx_processes`), take consistent copies:
```
copy <REPO_ROOT>\v2_lane.db               v2_lane.db.pre_activation_<UTC>
copy <REPO_ROOT>\v2_service_status.json   v2_service_status.json.pre_activation_<UTC>
copy <REPO_ROOT>\.env                     env.pre_activation_<UTC>          [KEEP OUTSIDE any tracked dir; contains secrets]
copy %USERPROFILE%\.talonx\ingestion_ledger.db  ingestion_ledger.db.pre_activation_<UTC>
```
No writer is running at this point (§0 confirmed it), so a plain file copy of
each SQLite file is consistent — WAL/SHM sidecars are checkpointed by
`PRAGMA wal_checkpoint(TRUNCATE)` first if present, so the copy is a single
consistent file, not a copy-plus-stale-journal. Verify the backup before
proceeding: `certutil -hashfile v2_lane.db.pre_activation_<UTC> MD5` must
equal the live file's hash.

### Automatic schema changes (all additive)

| store | change | idempotent? |
|---|---|---|
| `ingestion_ledger.db` → `intelligence_delivery` | `ALTER TABLE ... ADD COLUMN attempt_id / in_flight_since_utc / transport_message_id` on first `DeliveryOutbox` open (checked against `PRAGMA table_info` first) | yes — only added if missing |
| `ingestion_ledger.db` | `CREATE TABLE IF NOT EXISTS` for `schema_meta`, `intelligence_delivery`, `intelligence_delivery_log`, `insider_filings`, `insider_transactions`, `insider_filing_evidence`, etc. | yes |
| `v2_lane.db` → `v2_alert_outbox` | `ALTER TABLE ... ADD COLUMN deliver_by_utc TEXT` (pre-existing, not from this task) | yes |
| `v2_lane.db` | `CREATE TABLE IF NOT EXISTS` for `processed_episodes`, `positions`, `trades`, `cooldowns`, `portfolio`, `pending_entry_intents`, `v2_alert_outbox` | yes |

None of these are "no migration" — opening the stores DOES perform
`ALTER`/`CREATE` statements every time. Safe because strictly additive and
idempotent, not because nothing happens.

## 2. Isolated backlog check (copy only — production untouched here)

**`event_time_lookup=None` must NEVER be used** — it silently drops the real
event-acceptance-time basis the live runtime uses. Use the same lookup shape
`runner.py::deliver_cycle` uses (join `text_events.accepted_at_utc`), at the
**actual current cutoff**, not a reused prior number:
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
now = d.datetime.now(d.timezone.utc)   # the REAL activation instant
expired = ob.expire_stale(now=now, max_age_seconds=None, event_time_lookup=event_time.get)
print(len(expired), 'expired at', now.isoformat())
ob.close()
"
```
Review the counts, and a sample of both EXPIRED and still-PENDING
dispositions, before proceeding. Delete the throwaway copy afterward.
Production `ingestion_ledger.db` is **not** touched by this step.

## 3. Apply the reviewed migration + approved expiry to production

Only after step 2's rehearsal passes review, and **with all writers still
stopped**:
```
python -c "
import sqlite3, datetime as d
from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
import pathlib
path = str(pathlib.Path.home() / '.talonx' / 'ingestion_ledger.db')
con = sqlite3.connect(path)
event_time = {}
for eid, acc in con.execute('SELECT event_id, accepted_at_utc FROM text_events WHERE accepted_at_utc IS NOT NULL'):
    try: event_time[eid] = d.datetime.fromisoformat(str(acc).replace('Z','+00:00'))
    except Exception: pass
con.close()
ob = DeliveryOutbox(path)   # opening applies the additive migration for real
now = d.datetime.now(d.timezone.utc)
expired = ob.expire_stale(now=now, max_age_seconds=None, event_time_lookup=event_time.get)
print(len(expired), 'expired at', now.isoformat())
ob.close()
"
```
Auditable, not destructive: `EXPIRED` is a terminal state with a log line —
**no row is ever deleted, and no expired row is ever marked SENT.** Never
rewrite historical `accepted_at_utc` / acceptance timestamps.

Verify logical continuity immediately after (compare against the §1
pre-activation snapshot): cash, positions, trades, the ABCL
`SKIPPED_ENTRY_STALE` disposition, pending entry intents, and delivery
history (state counts, any `attempt_id`/`transport_message_id` values) all
preserved. **A changed file hash here is expected** (the migration + expiry
both write) — document it, do not treat it as an anomaly.

## 4. Configure Intelligence-card delivery — env vars BEFORE step 5

There is exactly **one** Intelligence producer/drainer: the `intelligence`
`ComponentSpec` in `talonx_ops.supervisor.default_talonx_components()` —
spawned automatically by `talonx_ops.supervisor run`, which `prospective
start` (step 5) launches. Never run a second, separate
`poll --send` process — that would race the supervised one. See
`docs/audits/task117_final_activation_corrections/supervised_intelligence.md`.

Config propagation: `talonx_ops.supervisor.SubprocessRunner.spawn()` builds
every child's environment as `env = dict(os.environ)` — the supervisor's own
environment (inherited from `prospective start`'s environment) reaches the
supervised `intelligence` child unmodified. So these are exported **now,
before step 5**, in the same shell:
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
Telegram configured. Missing config is visible, not silently ON: with either
var unset the supervised child logs `mode=disabled` every cycle and the
dashboard's Card-delivery block stays at 0 SENT with an explicit note
explaining why.

After step 3's expiry, the first enabled cycle has only genuinely-fresh rows
— it cannot flood Telegram (`process_pending` expires first, then caps at
`deliver_cards_per_cycle`; `process_digest` aggregates one message per 6 h
bucket with restart-safe dedup).

## 5. Start the V2 trading stack (atomic, single-writer)

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
  (`REFUSED_ALREADY_RUNNING`, exit 3). `--force` does **not** break a live
  lock.
- Spawns exactly: `talonx_ops.supervisor run` (which itself spawns the
  `intelligence` component configured in step 4, plus `original`/
  `experimental`/`dashboard`) + one `talonx_v2.run --mode live
  --form4-source insider` companion (never `supervisor include_v2` — Task
  112T T1: that path reads stale parquet). `--deliver --transport telegram`
  is passed to the companion here so there is no second manual companion.
- The command then re-polls `verify_running` + the heartbeat file every 3 s
  for up to `GRACE_S = 120` s — this loop **is** the STARTING → READY/FAILED
  resolution mechanism.

### Readiness gate (verdict)
`READY` requires **all** of: `supervisor_alive`, `v2_companion_alive`,
`dashboard_8787`, **and** a fresh first-tick heartbeat (`age < 180 s`,
`strategy_version` present). Exit codes: `READY 0 · STARTING 0 · NOT_STARTED
2 · REFUSED 3 · FAILED_WITH_RESIDUALS 4`. On `FAILED_WITH_RESIDUALS` the
command runs an ownership-safe `stop_stack` and writes `start_cleanup.json`.

## 6. Acceptance

Confirm on `http://127.0.0.1:8787`:
- **Active V2**: fingerprint `11107198c5b81237`, real capital BLOCKED,
  `$300,000` cash, scope = 39-name allowlist, `--live-lookback-days 45` and
  `--pricing-mode composite-yf` effective, first heartbeat fresh.
- **Intelligence → Card delivery**: both gates enabled, by-state counts,
  sent-today, last card/digest sent.
- **Paper/EOD → Official Telegram — last confirmed send**: reflects the
  connectivity-test send (message ID recorded).
- **Overview**: `intelligence` producer heartbeat (confirms the ONE
  supervised process, not a second manual one); Experimental external sends
  BLOCKED.

## 7. End-of-day (OPERATOR-DRIVEN)

```
python -m talonx_ops.prospective close          # add --no-shutdown to keep the stack up
```
EOD reconciliation is **operator-driven**. The checkpoint daemon
(`session-loop`, spawned by `start` unless `--every 0`) runs 30-minute
CRITICAL-only checkpoints and `events.jsonl` — it does **not** run EOD
reconciliation and does not flatten positions. `prospective close`:
- writes `eod_session_report`, `lane_accounting_eod.json`
  (`build_lane_accounting`), reconciliation JSON;
- then performs an **ownership-safe** `stop_stack` (reaps only pid-tree
  members verified by create-time + cmdline; removes the startlock only when
  no residual remains) unless `--no-shutdown`.
No new recurring job is introduced by this release.

## 8. Rollback

See `docs/audits/task117_final_activation_corrections/rollback.md` (the
authoritative, corrected procedure — prefers compatible-code rollback over
any database restore since every schema change here is additive, and never
blindly restores over post-activation writes). Do not use any DB-restore
step as a routine/first-resort rollback action.

## Supported commands referenced (all real)

| command | purpose |
|---|---|
| `python -m talonx_ops.prospective preflight --expected-sha <SHA>` | read-only gate |
| `python -m talonx_ops.prospective start [flags above]` | atomic single-writer stack start + verdict |
| `python -m talonx_ops.prospective status` | current stack + verdict |
| `python -m talonx_ops.prospective close [--no-shutdown] [--force]` | EOD reconciliation + ownership-safe shutdown |
| `python dashboard_web.py --port 8787` | primary cockpit (started by the supervisor under `start`) |
