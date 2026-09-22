# Next prospective paper day: runbook (V2-PAPER-RC1, frozen v2-paper-rc1)

Operating principle: **start early → confirm ingestion is current → keep ingestion running through the actionable window → observe V2 → EOD reconciliation → classify every potential opportunity → update the economic ledger.**

This runbook uses the same frozen release, the same `V2-PAPER-RC1` campaign (never re-initialized), Alpaca SIP `1Day` with split-only adjustment and no fallback, Signal/Sentinel routing, and Lab OFF. There are no code, strategy, provider or accounting changes. Use one PowerShell window. Never print token or key values.

## Why coverage matters (ADC lesson)
A cluster is actionable only between the SEC acceptance of its activating filing and the **RTH open of its entry session**, which is the next session. TalonX must ingest the filing and run a V2 tick inside that window. Otherwise the frozen cold-start rule correctly refuses it (`SKIPPED_NO_PRIOR_INTENT`), and the day records a miss that cannot be recovered. ADC was missed this way because the ingester was offline from 2026-09-16 to 09-20.

- **Run every XNYS trading day.** A skipped trading day can lose any cluster whose entry session is that day or the next.
- **Start well before the open** (target 08:00 Europe/London). Filings accepted after the previous day's stop are ingested on the morning catch-up and are still admissible before the RTH open. Allow about 30 minutes for catch-up.
- **Keep the stack running until the post-close EOD.** Filings accepted during RTH get their entry session on the next day, and their intent is created that same afternoon.
- Take the open, close and early-close times from the exchange calendar (runtime `eod.close_utc`). Never hardcode them.

## Operational requirement: continuous insider-ingestion coverage

A prospective day counts as **`FULL_PROSPECTIVE_COVERAGE = YES`** only when all of these hold:

1. The insider ingester was running **before** the actionable pre-open period. Its `started_at_utc` is before that session's RTH open, and early enough to catch up overnight filings (about 30 min).
2. It **stayed running** through the day's filing and admission windows, from start until the controlled stop after close, with no unplanned restart.
3. The **final SEC poll is current**: `last_cycle.at_utc` is within a few poll intervals of the controlled stop, with `symbols_failed = 0`.
4. Source freshness **never entered an unhandled `STALE`/`DOWN`** state. Any `DEGRADED_HEALTH` Sentinel event is recorded with its start and recovery times and handled.
5. Every detected gap (a checkpoint `processing_log_age_s` > about 900 s, a restart, or a degradation) is **recorded** in the session evidence.
6. Every opportunity whose activating filing was accepted while ingestion was offline is classified **`MISSED_DUE_TO_INGESTION_DOWNTIME`**.

Evidence quality: the ingester heartbeat and metrics files are overwritten each cycle, and there is no durable per-poll history. Continuity is therefore established from 30-minute checkpoints, the final heartbeat, and ingestion-row timestamps. With no contrary evidence, record **`FULL_PROSPECTIVE_COVERAGE: YES_WITH_INFERENCE`**. Use `YES` only if every checkpoint shows a fresh heartbeat and no gap. Use **`NO`** if any condition fails.

A `NO` day still provides infrastructure evidence. Its opportunity counts and any profitability evidence must, however, carry an explicit coverage-gap note. Never change trading code to compensate for downtime.

**Filing dates:** V2 maps filings to sessions **only** by SEC `filingDate` (`insider_*.filing_date`, persisted on ingest). In release mode, a code-P record without it excludes its issuer (`MISSING_AUTHORITATIVE_FILING_DATE`, visible in V2 status `source.missing_authoritative_filing_date`). The release gate check `authoritative_filing_date_readiness` must be PASS. If it is FAIL, run `.venv\Scripts\python.exe -m talonx_ingest.intelligence.insider.filing_date_backfill --apply` (idempotent; it writes `filing_date` only), then re-run the gate.

## 1. Preflight (about 08:00 UK)
```powershell
cd C:\workspace\TalonX
git fetch origin; git checkout main; git pull --ff-only origin main
git status --porcelain=v1        # tracked tree must be clean (untracked *.db-shm/-wal/status.json are operational)
git merge-base --is-ancestor a56ec8c8d10adb36a113ebd373204f297c230081 HEAD; $?   # True
Get-Process python -ErrorAction SilentlyContinue   # expect none; stale status/pid files without a process are not a running instance
$env:TALONX_V2_CAMPAIGN_ID='V2-PAPER-RC1'
$env:TALONX_V2_DB_PATH='v2_release_rc1.db'
$env:TALONX_V2_STATUS_PATH='v2_release_rc1_status.json'
$env:TALONX_V2_STARTING_CASH_USD='100000'
$env:TALONX_V2_ALLOCATION_USD='10000'
$env:TALONX_V2_EXECUTION_MODE='PAPER'
$env:TALONX_NOTIFY_DB_PATH='v2_release_rc1_notifications.db'
.venv\Scripts\python.exe -m talonx_v2.release_gate --verify-campaign   # clean=true; only SKIPPED_* rows allowed
.venv\Scripts\python.exe -m talonx_v2.release_gate                     # status READY (incl. authoritative_filing_date_readiness PASS); strategy e2acf6454789217e, provider ac5e51aa3599d6c9
```
Stop if anything is NOT_READY, a fingerprint mismatches, the campaign is wrong, or a legacy `v2_lane.db` / shared `notifications.db` is selected.

## 2. Start (same window)
```powershell
.venv\Scripts\python.exe -m talonx_ops.prospective start --release --expected-sha a56ec8c --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 --execution-scope resolved-active-watchlist --deliver --transport telegram
```
Expect startup verdict `READY`. Record the start time and the session dir `results\prospective_<date>\`. Send `/ping` to TalonX Signal and **record the reply text in the session evidence** (Session 02 did not capture it).

## 3. Ingestion coverage capture (read-only file reads, no second service process)
Run this at start, once ingestion is current, before the open, and at close:
```powershell
$h = Get-Content "$env:USERPROFILE\.talonx\intelligence\service.heartbeat.json" -Raw | ConvertFrom-Json
"ingester pid=$($h.pid) started=$($h.metrics.started_at_utc) heartbeat=$($h.heartbeat_at_utc) mode=$($h.mode)"
"last poll=$($h.last_cycle.at_utc) freshness=$($h.last_cycle.freshness) new_form4=$($h.last_cycle.new_form4) errors=$(@($h.last_cycle.errors).Count)"
.venv\Scripts\python.exe -m talonx_ops.prospective status          # service_health, data_state, critical_flags
```
Also read `results\prospective_<date>\checkpoints\latest.json`: `intelligence.processing_log_age_s`, `intelligence.newest_insider_event_utc`, and `supervisor.producers.intelligence`.

Record these:

| Item | Source |
|---|---|
| Ingester start time / uptime | `metrics.started_at_utc` (uptime = now − start) |
| Last successful SEC poll | `last_cycle.at_utc` + `freshness` (heartbeat) |
| Filing-store freshness | checkpoint `processing_log_age_s`, `newest_insider_event_utc` |
| Polling gaps | any checkpoint with `processing_log_age_s` > about 900 s, or a Sentinel `DEGRADED_HEALTH` (from `v2_release_rc1_notifications.db`), with start and recovery times |
| Operational through the actionable window | session start before the RTH open, 0 unplanned restarts, controlled stop after close |
| **FULL_PROSPECTIVE_COVERAGE** | `YES` / `YES_WITH_INFERENCE` / `NO`, per the operational requirement above |
| Missing SEC filing dates | V2 status `source.missing_authoritative_filing_date.count` (expected 0) |

**Pre-open GO requires** the ingester heartbeat to be fresh, `last_cycle.freshness` not `DOWN`/`STALE`, V2 `data_state=CURRENT`, and all other release checks green. If ingestion cannot get current before the open, record that and classify any affected cluster as category 5. Do not bypass anything.

## 4. During the session
The checkpoint daemon writes every 30 min and `events.jsonl` carries only notable events. Look in at open, midday and late session with `prospective status`. On any real opportunity, verify the chain (qualification → liquidity/account gates → SIP price → reservation → paper fill → ledger → Signal) without intervening.

## 5. Close and EOD (after the calendar close, inside the grace window)
```powershell
.venv\Scripts\python.exe -m talonx_ops.prospective close
```
Expect `PASS` or `PASS_WITH_FINDINGS` with 0 residual processes. `base_reconciliation: PARTIAL` (no PIV reader) and a PENDING `SHUTDOWN` Sentinel notice are known and accepted. Capture the ingestion block (section 3) one more time just before `close`.

## 6. Classify every potential opportunity (after close)
For every episode with ≥2 distinct owners in the 45-day window, read the ledger and ingestion data **read-only**. Open SQLite with `?mode=ro`, and rebuild episodes only against a *copy* of `ingestion_ledger.db`, because `InsiderStore()` writes its schema on open. Record:

- `processed_episodes.disposition` / `eligible_entry_session`
- `pending_entry_intents` / `positions` / `trades` for the `episode_id`
- the activating filing's `filing_date` (SEC `filingDate`, the calendar date for session mapping), its SEC acceptance instant (from the raw SGML header when an exact time matters; `accepted_at_utc` has mixed legacy semantics), and `insider_filings.ingested_at_utc`
- whether a prospective session covered SEC-acceptance → entry-session RTH open

Assign exactly one category from [README.md](README.md) §2 and apply its precedence. Do **not** classify from the funnel's `fresh_eligible` / `REVIEW_POSSIBLE_SUPPRESSION` label, because that label ignores terminal state. A day with no ≥2-owner cluster whose entry session falls on or after the campaign start is `NO_QUALIFYING_CLUSTER`.

## 7. Evidence
Create `docs/research/evidence/v2_prospective_<date>/`. Copy in `eod.json`, `final_report.md`, the first and last checkpoints, `release_gate.json`, `preflight_poststart.json`, `events.jsonl`, the ingestion-coverage table, the `/ping` reply, and the opportunity classification. Update [ECONOMIC_LEDGER.md](ECONOMIC_LEDGER.md) sections A–C. Scan for secrets. Never commit `*.db`, `*.db-shm`/`-wal`, status or pid files. `main` is PR-protected, so open one evidence-only PR.

Report `PROFITABILITY VALIDATION: NOT_COMPLETE` until the sample supports otherwise. Do not tune.
