# Morning handoff — Task 117 overnight release closure

**Verdict: `READY_FOR_CONTROLLED_ACTIVATION_REVIEW`.**
Not a claim that all possible defects are eliminated — see `remaining_blockers.md`.

## SHAs

| | value |
|---|---|
| branch | `research/talonx-strategy-validation` |
| starting SHA | `b485e3f86508ae5e75aa1ed8a9cd71410c76e7e7` |
| final SHA | `__FINAL_SHA__` |
| previous SHA (rollback target) | `b485e3f86508ae5e75aa1ed8a9cd71410c76e7e7` |
| push | `__PUSH_RESULT__` |
| V2 fingerprint | `11107198c5b81237` — **unchanged** |
| V1 fingerprint | `2ae6216bca70` — **unchanged** |
| production `ingestion_ledger.db` md5 | `2ae2105c6f51a4af4b3b80dc06e5f30f` — **unchanged** |
| production `v2_lane.db` | **absent** (fresh Day-1) — not created, not mutated |
| Redis `talonx-redis` | up 41 h, healthy, not flushed / restarted / written |
| external messages sent | **0** |
| app / test processes left running | **0** (verified) |

## What closed tonight (with evidence)

| area | outcome |
|---|---|
| **§1 delivery reliability** | mode validated before any mutation/network (`InvalidDeliveryMode`); durable `IN_FLIGHT` claim committed **before** the send; competing drainer blocked by atomic `WHERE state='PENDING'`; restart → `recover_in_flight` → `AMBIGUOUS` (never blind-retried); transport `send(retry_ambiguous=False)` raises `TelegramAmbiguousError` on timeout/network; `RetryAfter`/429 stays retryable; `message_id` captured on `SENT`; decision time = actual send time; unexpected errors surface in `DrainResult.errors` + `summary["ok"]=False`, never swallowed. 10 `test_task117_delivery_reliability.py` + 647 delivery/telegram/dispatch regression. |
| **§2 digest / freshness / backlog** | `process_digest` aggregates DIGEST rows into ONE message per 6 h bucket, restart-safe via `last_digest_bucket`; freshness = older of (event acceptance time, enqueue time) — old filings enqueued today are not fresh; auditable expiry (no deletion, no EXPIRED→SENT); backlog recomputed at cutoffs (9,843 → 9,841 EXPIRED / 2 PENDING @ 2026-09-11T13:30Z; 9,843 EXPIRED @ 2026-09-12); 23 CRITICAL reviewed, none sent; first enabled cycle bounded (0–2 IMMEDIATE + ≤1 digest). Production untouched. 5 `test_task117_digest_semantics.py`. |
| **§3 atomic startup** | `SingleWriterLock` (`os.open O_CREAT\|O_EXCL`) over check→spawn→registration; `--force` cannot break a live lock; stale lock broken only after PID/ledger-identity check; `startup_verdict` READY requires supervisor + companion + **dashboard_8787** + fresh heartbeat; `STARTING`→`READY/FAILED` resolved by the 120 s re-poll loop in `cmd_start`; `FAILED_WITH_RESIDUALS` self-heals. **Real 2-subprocess** concurrent test proves exactly one owner. 5 lock + 16 verdict tests. |
| **§4 dashboard + accounting** | actual :8787 SPA rendered vs isolated fixture (7 `ISOLATED_FIXTURE_*.png`); new **Card delivery** (6 states) + **Official Telegram — last confirmed send** cards in read model **and** SPA frontend; V2 5-signal health split, scoped funnel, EOD state, false-zero guard all visible. Accounting: no throttle/cooldown/reval records exist → residual is `UNEXPLAINED_FROM_RECORDS`, not defined by arithmetic; 16:24 ping `NOT_RECONSTRUCTABLE`; 94-gap `SUPERSEDED_BY_FINAL_DAY_RECONCILIATION`; comingled Redis counter not shown as official publications. 4 lane-accounting + 445 dashboard/prospective regression. |
| **§5 timestamp contract** | genuine `Z`/`+00:00` kept as UTC (single `astimezone`); naive read only under explicit source contract; SGML-Eastern path separate (implemented, tested, not wired); caller scan (`sessions.to_et`, `insider/store._iso/_dt`) all guard `tzinfo is None` — no double conversion; no production history shifted (Task E manifest 0 VERIFIED_CORRECTION); S1–S3 ~4 h anomaly stays `UNRESOLVED` and visible. 194 timestamp/edgar/insider/v2 regression. |
| **§6 bounded rehearsal** | `test_task117_release_rehearsal.py::test_bounded_release_rehearsal` → `release_rehearsal.json` `overall_PASS: true` — disabled→enabled same event, fresh+stale backlog, digest schedule + restart dedup, clean transient (retry-eligible), timeout after possible acceptance → AMBIGUOUS (not retried), restart with in-flight → recovered AMBIGUOUS, two competing starts → one owner + `--force` refused. V2 source-failure-with-open-position in `test_task117_overnight_e2e.py`. No dup delivery / false SENT / dup writer / lost pending; ownership-safe release. No full-day disabled live session run. |
| **§7 profitability handoff** | `profitability_research_contract.md` written; isolated worktree `C:\workspace\TalonX-task118-profitability` (branch `research/talonx-profitability-2026-09`) created from the release SHA; promotion criteria fixed before any tuning; no run executed, nothing merged into the release branch, no strategy change. |
| **§8 package** | this directory — 11 files + 7 screenshots; `deployment_candidate.md` has the exact supported commands/flags/config propagation/backup/readiness gates; EOD described as operator-driven `prospective close` (checkpoint daemon does not reconcile); coherent commit + normal push. |

## Delivery cancellation / restart / invalid-mode results

- **invalid mode** (`"ENABLED "`, `"on"`, …): `InvalidDeliveryMode` raised before
  `recover_in_flight` / `expire_stale` / `pending` / any sender; row stays
  `PENDING`, `sender.calls == []`.
- **cancellation mid-send**: `_SendCancelled` / `asyncio.CancelledError` →
  `mark_ambiguous` **and** the exception re-propagates (cooperative shutdown).
- **restart with an in-flight attempt**: `recover_in_flight(stale_after=90 s)`
  → `AMBIGUOUS` with reason "outcome unknown, not retried"; a subsequent drain
  does **not** re-send it.
- **timeout after possible remote acceptance**: `TimeoutError` /
  `TelegramAmbiguousError` → `AMBIGUOUS`; second drain does not blind-retry
  (`sender.calls` unchanged).

## Atomic startup / --force results

- two `SingleWriterLock(led).acquire()` → 1 × `ACQUIRED` (rc 0), 1 ×
  `ConcurrentStartError` (rc 7); real subprocess test.
- `acquire(force=True)` against a **live** owner → `ConcurrentStartError` (force
  never bypasses an active ledger writer).
- `start_stack` releases the lock on any startup exception; nothing spawned when
  refused.
- verdict matrix: dashboard-missing → `STARTING` / `FAILED_WITH_RESIDUALS`,
  never `READY`.

## Rendered dashboard acceptance

7 sections rendered from the real `dashboard_web.py` against
`TALONX_HOME=<iso_home>`; `card_delivery` and `official_telegram_last_send`
reconciled field-by-field against the section JSON (`dashboard_acceptance.md`).

## Backlog disposition & untouched production state

Isolated copy only. 9,843 rows → at 2026-09-12 activation **all 9,843 EXPIRED,
0 SENT, 0 deleted**. Production `ingestion_ledger.db` md5 unchanged
`2ae2105c6f51a4af4b3b80dc06e5f30f`. No `v2_lane.db`, watchlist, backlog or Redis
mutation.

## Exact short activation procedure still requiring execution

Full detail in `deployment_candidate.md`. In brief:
1. `python -m talonx_ops.prospective preflight --expected-sha __FINAL_SHA__`
2. back up `v2_lane.db` / `ingestion_ledger.db` / `.env` (copy)
3. `python -m talonx_ops.prospective start --expected-sha __FINAL_SHA__ --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 5 --pricing-mode composite-yf --execution-scope resolved-active-watchlist --deliver --transport telegram` → wait for `READY` (sup + companion + :8787 + heartbeat)
4. drain the Intelligence backlog on a copy, apply `expire_stale` once to the live ledger while delivery is still disabled
5. `set TALONX_INTEL_DELIVER_CARDS=1 & set TALONX_INTEL_DRY_RUN_DELIVERY=0` then `python -m talonx_ingest.intelligence.service poll --duration 3600 --send --i-understand-external-send`
6. EOD: `python -m talonx_ops.prospective close`

## Profitability research — first action tomorrow

In `C:\workspace\TalonX-task118-profitability`: rebase onto `__FINAL_SHA__`,
produce `results/task118_profitability/INVENTORY.md` (datasets + prior-rejection
history), freeze the 39-CIK membership list with its resolution date — **then**
run deliverable A (exact V2 39-name baseline, 20 bps costs, chronological
holdout) through `talonx_research/replay_engine`. No tuning, no broad
optimisation. See `profitability_research_contract.md`.

## GitHub evidence

- Bundle: `docs/audits/task117_overnight_release_closure/` at `__FINAL_SHA__`
- Prior Task 117 bundles: `docs/audits/task117_output_closure/`,
  `docs/audits/task117_delivery_timestamp_completion/`, `docs/audits/2026-09-10/`
- Commit: `__FINAL_SHA__` on `research/talonx-strategy-validation` (pushed,
  no main merge, no force-push)
