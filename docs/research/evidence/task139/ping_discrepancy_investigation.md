# Priority Investigation — Live /ping Discrepancy (2026-09-15, during Task 139/140 cutover)

**Trigger**: operator-observed live `/ping` at `2026-09-15T02:55Z` reported
Intelligence collection at 39 effective symbols (previously 569), V2
admission PERMISSIVE (previously GATED), V2 execution scope still 626.
Also asked to classify 203 provider failures by reason/time window.

## 1. Captured configuration (no secrets)

- Original: `run_talonx.py`, argv has no relevant flags (market data /
  broad-discovery config is entirely env-driven for this component).
- Intelligence: `python -m talonx_ingest.intelligence.service poll
  --with-backfill` — **no CLI flag exists for broad discovery on this
  entrypoint**; controlled solely by `TALONX_INTEL_ENABLE_BROAD_DISCOVERY`.
- V2 companion argv: `...--enable-broad-discovery` present and correct.
- `.env` (206 lines): **does not contain** `TALONX_INTEL_ENABLE_BROAD_
  DISCOVERY` or `TALONX_V2_DURABLE_STORE_ENABLED` anywhere.
- Neither var set at Windows User, Machine, or current-session Process
  scope.

## 2. Live behavior vs. reporting

**Genuinely live behavior was wrong**, not a reporting artifact:
`~/.talonx/intelligence/service.heartbeat.json`'s `effective_symbols`
list (the list Intelligence's own poller/backfill actually iterate)
had exactly 39 entries immediately after the host-restart recovery —
confirmed by direct query, not inferred.

## 3. Admission PERMISSIVE — confirmed correct, NOT a regression

`talonx_v2/service.py`'s durable-admission gate reads
`TALONX_V2_DURABLE_STORE_ENABLED` (default unset → PERMISSIVE).
`docs/research/TASK131_RETROSPECTIVE.md` states explicitly and
authoritatively: **"`V2Service`'s own runtime default (outside pytest,
no env override) remains `False`, per the literal remediation
requirement."** This is the documented, intended, unchanged production
default for this deployment — not something lost by any restart. No
admission-blocking action was taken (none was warranted); reported here
instead of acted on, per the explicit preservation requirement not to
tune admission/strategy behavior.

## 4. Root cause: Intelligence's own broad-discovery toggle was never wired into the launcher

Task 132 (commit `aca1a4c`) correctly threaded `--enable-broad-discovery`
through to the **V2 companion's own argv**, and separately fixed `.env`
loading into the launcher process. But Intelligence's own broad-discovery
mode has **no CLI flag** (`broad_discovery.py`'s only control surface is
the env var) and was **never added to `.env`** — the only way it was ever
active in this deployment's history was an ad-hoc interactive shell
`export`/`$env:` set once before the very first `prospective start` of
this campaign (2026-09-08), sustained only because that terminal session
was never closed until the OS forced a reboot. No restart before
tonight's OS-update reboot ever had to reconstruct that state, because
none of them killed the interactive shell itself — only individual
supervised child processes. Tonight's full-host reboot is the first event
in this campaign's history to actually destroy it, exposing a latent gap
that existed the whole time.

## 5. Fix, verified live (not just via shell inspection)

`talonx_ops/prospective/proc.py`: `start_stack()`'s `enable_broad_
discovery` parameter now also sets `TALONX_INTEL_ENABLE_BROAD_DISCOVERY=1`
in the env merged into supervisor's own spawn, inherited by every child
supervisor launches. Never overrides an explicit shell/`.env` value
(checks both the `env` param and live `os.environ` first). Committed as
`9ee3ee0` with 3 new isolated tests
(`tests/test_task114_prospective.py`).

**Live verification after the minimal necessary managed restart**
(`stop_stack()` then `start_stack()` — both existing, supported
mechanisms; `close` was deliberately NOT used since `run_close()`
returns `NOT_DUE_YET` and performs no shutdown/reconciliation before the
session boundary, confirmed by reading its source before acting):

- Pre-restart snapshot: cash $300,000.00 (V2) / $10,000.00 (Original), 0
  positions, 0 pending intents, 0 IN_FLIGHT rows, AMBIGUOUS unchanged at 2,
  intelligence_delivery PENDING 171 / SENT 264 / EXPIRED 24313.
- `stop_stack()`: clean, `residual_talonx_processes: []`,
  `v2_lane_db_intact: true`, `startlock_released: true`.
- `start_stack(... --enable-broad-discovery ...)` at HEAD `9ee3ee0`:
  `startup verdict: READY`.
- **`effective_symbols` in the fresh heartbeat: 569 entries** (was 39) —
  the actual live collection list, verified by direct query.
- Post-restart accounting: matching on every specifically-compared value (cash, position/intent/row counts, outbox state totals -- not a full database byte-for-byte comparison) to the pre-restart snapshot
  above (same cash, same 0/0/0/2/171/264/24313 figures) — no drift, no
  duplicate effect.
- V2 fingerprint unchanged: `11107198c5b81237`.
- `admission_policy.mode` re-confirmed `PERMISSIVE` post-restart (§3 —
  correct, unchanged).
- Single owner per component confirmed via full process listing; dashboard
  `200 OK`.

## 6. Provider-failure classification (203→206 by the time of this check)

`metrics:2026-09-15:ingest:provider_requests_failed` = 206,
`metrics:2026-09-15:ingest:provider_err_provider_schema_error` = 206 —
**100% one reason, one category**: `PROVIDER_SCHEMA_ERROR`, and every
individual log line (`.run/logs/talonx.log`, grep `[provider `) carries
the identical underlying cause: `'currentTradingPeriod'` (a field
yfinance intermittently omits outside active trading hours). The SAME
reason/rate was already present the prior day
(`metrics:2026-09-14:...provider_err_provider_schema_error` = 70) —
**pre-existing, not new**.

**Time-window breakdown (local hour buckets, confirmed NOT concentrated
in the current process's uptime)**:

| local hour | UTC equivalent | count | relative to reboot (01:44-01:47Z) |
|---|---|---|---|
| 01:xx | 00:00-00:59Z | 100 | before |
| 02:xx | 01:00-01:59Z | 96 | before (spans up to the reboot) |
| 03:xx | 02:00-02:59Z | 8 | after (post first-recovery restart ~02:30Z) |
| 04:xx | 03:00-03:59Z | 3 (so far) | after |

**196 of 206 (≈95%) occurred BEFORE the reboot**; only 11 have occurred
since, continuing at a similar low background rate — this is an ongoing,
low-severity, tolerated-by-design provider quirk (each failure only skips
that one symbol for one poll cycle; `market.state` stayed `HEALTHY`
throughout), not a new regression introduced by any restart tonight. No
code change made for this — correctly classified, not fixed, since it
predates this session's work entirely and is not a demonstrated defect
in TalonX's own code.
