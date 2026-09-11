# Resolved runtime paths and schema migrations (Task 117 final-activation A1)

## What was wrong

The prior `deployment_candidate.md` assumed `v2_lane.db` lived at
`%USERPROFILE%\.talonx\v2_lane.db` and reported it **absent** ("fresh
Day-1"). Both are wrong. `~/.talonx` is the legacy/Original dashboard home
(`TALONX_HOME` in `talonx_ops/dashboard_read.py`); it has never held the V2
ledger. The confusion happened because an earlier check queried the wrong
directory and found nothing there, then concluded "absent" instead of
searching further.

## Actual paths, traced from source

| store | actual path | resolved by |
|---|---|---|
| V2 campaign ledger | `<REPO_ROOT>\v2_lane.db` | `talonx_ops/prospective/paths.py`: `V2_DB_PATH = REPO_ROOT / "v2_lane.db"` |
| V2 status file | `<REPO_ROOT>\v2_service_status.json` | `paths.V2_STATUS_PATH` |
| Non-secret V2 env (4 vars) + secrets | `<REPO_ROOT>\.env` (gitignored) | `paths.resolve_env()` (env override → `.env` → frozen default) |
| SEC ingestion ledger (InsiderStore + Intelligence delivery outbox) | `%USERPROFILE%\.talonx\ingestion_ledger.db` | `TALONX_LEDGER_PATH` env, default in `talonx_ingest/config.py` (`LedgerConfig`) |
| Watchlist | `%USERPROFILE%\.talonx\watchlist.db` | `talonx_ops.watchlist_coverage` — legacy/Original home, not V2-specific |

`REPO_ROOT = Path(talonx_ops/prospective/paths.py).resolve().parents[2]`, i.e.
the repository root (`C:\workspace\TalonX`).

## The actual, established campaign ledger

Verified directly against the live file (md5 `29e57dbcd1a567fbc4bb0e73efdba95f`,
unchanged throughout this correction):

| field | value |
|---|---|
| `portfolio` cash | $300,000.00 |
| open positions | 0 |
| trades (all-time) | 0 |
| `processed_episodes` | 1 row: `07242bc857569f60` / ABCL / `SKIPPED_ENTRY_STALE` (Task 113, 2026-08-17 eligible, skipped as stale on 2026-09-08) |
| `pending_entry_intents` | 0 |
| `v2_alert_outbox` | 0 |

This is a **carried-forward campaign**, not a fresh one. The
ledger-continuity guard in `talonx_ops/prospective/preflight.py` already
encodes the correct rule for this: if `V2_DB_PATH` is unexpectedly missing at
activation time, it **fails closed** ("DO NOT recreate — carry-forward ledger
is missing") rather than seeding a replacement. `deployment_candidate.md`'s
corrected backup step follows the same rule explicitly.

## Automatic schema changes — enumerated, not glossed over

Opening either store via its real class **always** performs `CREATE TABLE IF
NOT EXISTS` for its full schema, and the following **additive** `ALTER TABLE`
statements when the target column is missing:

| store | table | change | source |
|---|---|---|---|
| `ingestion_ledger.db` | `intelligence_delivery` | `ADD COLUMN attempt_id TEXT`, `ADD COLUMN in_flight_since_utc TEXT`, `ADD COLUMN transport_message_id TEXT` | `outbox.py::DeliveryOutbox.__init__` (Task 117 §1B, this release) |
| `v2_lane.db` | `v2_alert_outbox` | `ADD COLUMN deliver_by_utc TEXT` | `talonx_v2/store.py` (pre-existing, not from this task) |

Both check `PRAGMA table_info(...)` first and only add a column that is
missing — safe to run repeatedly (idempotent) and safe to run against a
long-lived production file (additive-only; nothing existing is altered or
dropped).

## Rehearsal on isolated copies of the LIVE stores

Real copies of the live `v2_lane.db` and `ingestion_ledger.db` were made to an
isolated temp directory, opened through the real `V2Store` / `DeliveryOutbox`
classes (the exact code path `prospective start` / the Intelligence poll
loop use), and re-snapshotted:

| field | before | after |
|---|---|---|
| `portfolio` cash | 300000.0 | 300000.0 (unchanged) |
| `positions` | 0 rows | 0 rows |
| `trades` | 0 | 0 |
| `processed_episodes` | 1 row (ABCL `SKIPPED_ENTRY_STALE`) | same 1 row, byte-identical |
| `pending_entry_intents` | 0 rows | 0 rows |
| `v2_alert_outbox` | 0 rows | 0 rows |
| `intelligence_delivery` state counts | `{PENDING: 9843}` | `{PENDING: 9843}` (unchanged) |
| `intelligence_delivery` columns | 23 | 26 (3 new columns added, all `NULL`) |

Cash, positions, the stale ABCL disposition, intents and delivery history all
survive backup + migration intact. **The isolated copies were deleted
immediately after the rehearsal** — they contained a full copy of live
campaign/ingestion data and were never committed or left on disk.

## Production state verified unchanged (post-correction)

A **stray artifact from test isolation gaps** (see
`ownership_lifecycle_tests.md` §"Production-safety note") — a real
`v2_lane.db.startlock` and stale WAL/SHM sidecars next to the live ledger —
was found and removed during this work; the ledger's own content and md5
were confirmed unchanged before and after. The offending test now isolates
its lock onto a tmp path.

Final verification: `v2_lane.db` md5 `29e57dbcd1a567fbc4bb0e73efdba95f`
(unchanged from task start); `ingestion_ledger.db` md5 unchanged; no stray
lock/journal/WAL files remain next to either.
