# Task 72O -- Overnight Stabilisation: Morning Consolidated Report

1. **Starting branch/SHA:** research/talonx-strategy-validation @ `3fa0c51`
2. **Final branch/SHA:** research/talonx-strategy-validation @ `7ed27c7`
3. **Working-tree status:** clean, pushed, origin in sync.

## 4. Stage results
| Stage | Verdict |
|---|---|
| 0 -- Baseline/Task71S-R1 audit | PASS |
| 1 -- Automatic EOD + session identity | PASS |
| 2 -- Known full-suite failure | BLOCKED (evidence-only, root-caused) |
| 3 -- Offline profitability evidence | PASS (result: INCONCLUSIVE) |
| 4 -- Morning report | this document |

## 5. Commits and push status
- `3be9eac` `fix(piv): automate EOD reconciliation lifecycle` -- pushed.
- `7ed27c7` `research: add overnight long-only profitability evidence` -- pushed.
- No commit for Stage 2 (BLOCKED, no code change) or Stage 0 (read-only audit).

## 6. Files changed by stage
- Stage 1: `talonx_piv/{eod_lifecycle.py (new), session_runner.py, cli.py, events.py}`,
  `tests/test_task72o_eod_lifecycle.py` (new), Stage 1 result artifacts.
- Stage 2: none (evidence artifacts only).
- Stage 3: none (evidence artifacts only, via unmodified `talonx_backtest`/`scripts/run_historical_regimes.py`).

## 7. Test results
- Stage 1 targeted: 22/22 passed.
- Directly-related PIV suite (12 files): 220/220 passed.
- Full repository suite (Stage 1 checkpoint): **2159 passed, 1 failed
  (known, root-caused in Stage 2), 1 skipped, 15 xfailed.**
- Stage 2/3 introduced no code, so this full-suite result is still current
  at HEAD `7ed27c7`.

## 8. EOD/session lifecycle verdict
**PASS.** `talonx_piv/eod_lifecycle.py` now provides one idempotent,
ordered EOD state machine (EOD_STARTED -> ... -> SESSION_COMPLETED only
on PASSED), invoked from SessionRunner's guaranteed end-of-loop path
(scheduled completion, controlled shutdown, or a safely-caught unhandled
exception) and from the manual `cli.py eod` recovery path -- both always
linked to the ORIGINAL live `session_id`, never a second trading session.
22 tests cover idempotency, cross-date rejection, cancel/close/
reconciliation failure handling, and zero-broker-mutation-on-missing-
identity.

## 9. Regression-failure verdict
`test_run_historical_regimes.py::test_real_end_to_end_run_against_the_sample_trade_dataset`
root-caused: `examples/data/sample_AAPL_trade_1m.csv` (a non-protected
fixture) predates the 2026-08-21 commit `3c97d9d` that confirmed an
intentional RSI-curl confluence-zeroing rule; its one target candidate
now scores confluence=1 instead of >=2. Classified
`TEST_ISOLATION_DEFECT`. No protected file requires changing. Fix
(recalibrate the fixture to add a coincident MACD cross) deferred to a
follow-up task -- BLOCKED this task, not silently worked around, no
assertion weakened.

## 10. Eligible long-only candidates found
One: `TALONX_PRODUCTION_QUANTSCANNER_INTRADAY_LONG_ONLY_V1` (the
existing, frozen production strategy). No other candidate satisfied the
eligibility bar (see `stage3_candidate_inventory.csv`).

## 11. Profitability results and evidence classification
**INCONCLUSIVE.** AAPL, 2025-08-15..2025-12-31, established 5/5/10bps
cost: 6 signals generated, 0 published, 0 trades executed (99.5%+ of
bars rejected `LOW_VOLATILITY`). Zero trade-level evidence to compute
expectancy/PF/win-rate/bootstrap CI/concentration on. Not `REJECTED`
(would require a negative-edge sample); not close to
`VALIDATED_AND_REPLICATED` (no validation-period run was performed,
preregistered as unreachable this task upfront).

## 12. Holdouts consumed versus preserved
**Zero reserved holdouts accessed.** `data/historical_1m/task56_holdout`
and `task56_independent_family_holdout` were not opened, per
preregistration.

## 13. Downloads performed
None. Stage 3 used only already-downloaded data
(`data/historical_1m/task7b_alpaca_long_history`). Stage 0 involved no
network calls (pure git/code audit).

## 14. Broker/order mutations
**Zero, confirmed.** Stage 1's tests use `FakeBroker`/`NoOpTransport`
exclusively (no `requests`, no real HTTP). Stage 3 never imports
`talonx_piv` at all (pure historical backtest). No live PIV session was
started at any point overnight.

## 15. Remaining stabilisation issues
See `remaining_stabilization_plan.md`.

## 16-17. Recommendation
See `next_live_session_recommendation.md`.
