# V2 prospective paper session 03 (2026-09-23): first full day after the filing-date fix

| | |
|---|---|
| **SESSION VERDICT** | **`PROSPECTIVE_SESSION_PASS_WITH_FINDINGS`** |
| FULL_PROSPECTIVE_COVERAGE | **YES_WITH_INFERENCE** |
| EOD_RECONCILIATION | **PASS_WITH_FINDINGS** (base PARTIAL: no PIV reader) |
| PROFITABILITY_VALIDATION | **NOT_COMPLETE** (0 trades; no accepted sample-size criterion exists) |

## Release

- Main `9f0ab3819672afefb87c143d65ee837acee64903` (PR #17 merge). Release `v2-paper-rc1`, frozen `a56ec8c8`.
- Strategy fingerprint `e2acf6454789217e`, provider fingerprint `ac5e51aa3599d6c9`.
- Campaign `V2-PAPER-RC1`, PAPER, $100,000 start, $10,000 allocation. Not re-initialized.

## Preflight (all read-only)

- **Repository:** PASS. The tree was clean, the freeze preflight accepted HEAD, and PR #17 is in history.
- **Filing-date readiness:** 34,253 filings / 115,461 transactions / 1,467 purchase rows, with **0** NULL `filing_date` and 0 NULL purchase `filing_date`. `authoritative_filing_date_readiness` PASS. No backfill was run.
- **Campaign verify:** clean. $100,000 cash, 0 reserved, 0 positions, 0 intents, 0 blocks, 0 EXIT_UNRESOLVED.
- **Release gate:** **READY 21/21**, checked at 23:2xZ and again immediately before start. SIP QUALIFIED, Signal/Sentinel validation bound, Lab OFF, no account block.
- **Pre-start ingestion:** READY. The store was healthy and the last run FRESH with 0 errors. The known gap since 20:02Z 09-22 is recorded in `INGESTION_COVERAGE.md`.

## Startup and /ping

- The stack started at **2026-09-23 06:47:21Z (07:47 BST)**; startup verdict READY. PIDs: supervisor 8932, V2 companion 14592, checkpoint daemon 3632, ingester 7272. Restarts: **0**.
- **/ping PASS** at 06:50Z. It showed RUNNING, Release mode ON, V2-PAPER-RC1 (PAPER) cash 100000.0, alpaca SIP split `V2_RELEASE_PRICE_CONTRACT@1 (ac5e51aa3599d6c9)` fallback NONE, no account blocks, EXIT_UNRESOLVED 0, discovery 39/39. Verbatim copy: `extracts/ping_reply_0650Z.txt`.
- **PRE_OPEN_GO: YES.** Every checkpoint from 07:17Z to 13:17Z showed V2 HEALTHY, data CURRENT, market HEALTHY, ingestion current (log age ≤ 149 s), campaign $100k with 0 blocks and 0 EXIT_UNRESOLVED, and no critical invariant. This GO is established from the autonomous checkpoints. The operator did not interactively re-check at the open, and I was not re-invoked between 06:50Z and 20:13Z.

## Day summary

- The full regular session (13:30Z–20:00Z) was observed by 27 checkpoints and a final EOD checkpoint.
- **V2 funnel:** scope 39. Code-P 11 in the window, **1 new today** (ADC). 2 episodes (both pre-existing and terminal). **0 new qualifying clusters, 0 intents, 0 fills, 0 positions, 0 exits, 0 EXIT_UNRESOLVED.**
- **Why zero trades:** no new ≥2-owner cluster formed. ADC's new third-insider filing started a new clustering window alone (`OPPORTUNITIES.md`). Day-level classification: `NO_QUALIFYING_CLUSTER`. There were no operational misses and no implementation defects.
- **Filing-date fix, live:** 1 new relevant filing. Stored `filing_date` = SEC `filingDate` (2026-09-23). `MISSING_AUTHORITATIVE_FILING_DATE` 0, with release fail-closed active (`required: true`).
- **Provider:** SIP HEALTHY, 0 failures, 0 429s, no stale data, no CSV fallback.
- **Notifications:** V2 Signal TRADE_EVENT sent 0 / failed 0. Sentinel: STARTUP, DEGRADED_HEALTH (transient Intelligence), SHUTDOWN PENDING. Stale test-fixture alerts: 0. Intelligence `[INFO]` cards (a separate lane): **2 SENT** (ADC 11:03:11Z, AFL 13:03:08Z) and 4 pending (see findings).
- **Economics (ACTUAL):** 0 trades. Realized $0.00, unrealized $0.00, dividends $0.00, total return $0.00.

## Findings

| Finding | Classification |
|---|---|
| Stack start was delayed from ~00:02Z to 06:47Z (watcher fired late, probably machine sleep), leaving a 10 h 45 m pre-start ingestion gap that ended 6 h 43 m before the open. No code-P filing fell in the gap. | ENVIRONMENT / operating discipline (non-blocking) |
| Intelligence `PROCESSING_OR_INPUT_DEGRADED` around 12:53Z. It recovered within one checkpoint and also occurred around 13:02Z on 2026-09-22 (a recurring near-daily transient). V2 was unaffected. | BOUNDED_FOLLOWUP (Intelligence lane) |
| SHUTDOWN Sentinel notice PENDING at stop; the prior day's one is now EXPIRED (as designed) | BOUNDED_FOLLOWUP (known) |
| Funnel `REVIEW_POSSIBLE_SUPPRESSION` label from ADC's terminal episode | BOUNDED_OBSERVABILITY_FOLLOWUP (known) |
| `base_reconciliation` PARTIAL (no PIV reader) | EXPECTED_BEHAVIOUR |
| SEC JSON still showed ET-labelled acceptance 13 h after filing (re-render timing irregular) | Observation. No decision impact after PR #17. |
| **Intelligence cards were delivered to Telegram while the release gate reported "Intelligence card delivery is OFF".** 2 `[INFO]` cards were SENT today: ADC at 11:03:11Z (3-insider buying summary) and AFL at 13:03:08Z (insider selling). By design (Task 140, `talonx_ops/prospective/proc.py:266-270`), `prospective start --deliver --transport telegram` sets `TALONX_INTEL_DELIVER_CARDS=1` for the supervised Intelligence process. The gate reads only the operator shell env before start, so it reported PASS/OFF instead of WARN/ON. The cards are informational, not V2 trade events, and READY would still hold. | BOUNDED_FOLLOWUP (gate disclosure accuracy) |
| **The delivered ADC card displays the wrong source time:** "Source: 2026-09-23 07:00 UTC (source age: 4.0h)". The true SEC acceptance is 11:00:20 UTC (raw SGML 07:00:20 ET), received about 1.4 min later. The card renders the mixed-semantics `accepted_at_utc` (ET wall-clock labelled UTC for fresh ingests). User-visible, with no V2 decision impact. | BOUNDED_FOLLOWUP (Intelligence rendering; same root cause as PR #17's timestamp finding) |
| Pre-open GO and open checkpoints came from the autonomous daemon, not interactive operator checks | Process note |

No release blockers.

## Files

[CHECKPOINTS.md](CHECKPOINTS.md), [OPPORTUNITIES.md](OPPORTUNITIES.md), [INGESTION_COVERAGE.md](INGESTION_COVERAGE.md), [EOD.md](EOD.md), and `extracts/` (eod.json, final_report.md, release_gate.json, preflight_poststart.json, events.jsonl, first/late/EOD checkpoints, the /ping reply).

## Next

Continue accumulating prospective V2 opportunities and economic outcomes on the same frozen strategy and campaign.
