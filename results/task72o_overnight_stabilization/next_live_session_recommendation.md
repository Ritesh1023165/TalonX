# Next Live PAPER Session -- Recommendation

## Recommendation: **GO**

Scope: **operational/observational infrastructure session only** -- this
is explicitly NOT an alpha-validation session (no candidate reached
`VALIDATED_AND_REPLICATED`; the one candidate evaluated overnight is
`INCONCLUSIVE`).

## Gate-by-gate check

| Gate | Status |
|---|---|
| Task 71S-R1 remains sound | ✅ Re-audited Stage 0: on_bars unreachable from widened monitoring, recovery cannot bypass readiness, no alpha/order path changed. |
| Automatic EOD lifecycle passes | ✅ Stage 1: 22/22 tests, idempotent, linked to original live session_id, SESSION_COMPLETED gated on PASSED. |
| Repository is clean | ✅ HEAD `7ed27c7`, clean, pushed, origin in sync. |
| Runtime SHA/config are known | ✅ `7ed27c7`; config_hash unchanged from repository default. |
| PAPER-only enforcement intact | ✅ No protected file touched; no broker/order code changed; `talonx_piv/broker.py`/`lifecycle.py` untouched this task. |
| No unexplained regression exists | ✅ The one known full-suite failure is explained (Stage 2 root cause: stale fixture, `TEST_ISOLATION_DEFECT`), not unexplained. Still failing, but understood. |
| Clear session objective | ✅ Verify the new EOD lifecycle (Stage 1) fires correctly end-to-end in a real live session; continue observational monitoring per Task 71S-R1's freshness/coverage semantics. |

## Explicit session objective for the next live session

1. Confirm `EOD_STARTED -> ... -> SESSION_COMPLETED` fires automatically
   at 15:50 ET scheduled completion (or kill-switch), WITHOUT a manual
   `cli.py eod` invocation, and that every EOD_* event carries the SAME
   `session_id` as `PAPER_SESSION_STARTED`.
2. Confirm `freshness_report.json` is correctly stamped with
   session_id/trading_date_et/runtime_sha/config_hash at session end.
3. Observe (do not act on) per-symbol rolling coverage/gap classification
   in normal live conditions -- this remains observational evidence, not
   a trading signal.

## What would change this to NO-GO
- Any protected file (`talonx_quant/{strategy,indicators,consumer,config}.py`)
  showing an unstaged/uncommitted diff at session start.
- The full-suite failure count increasing beyond the one known, explained
  case.
- Any evidence that Stage 1's EOD lifecycle was reverted or bypassed.
