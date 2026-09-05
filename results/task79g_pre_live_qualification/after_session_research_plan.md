# Task 79G — Weekend Research Plan (PREPARATION ONLY — not started)

**No hypothesis search, backtest batch, or data access was performed to produce this document.**
It exists so that IF Task 80's session completes cleanly and heavy research resumes afterward,
that work has a bounded, pre-agreed shape rather than being improvised.

## Prerequisite gate (must ALL be true before heavy research begins)

1. Session processes have stopped (no `supervise`/`start` process, no residual
   `ExecutionOwnership` lock held for the account — verify via
   `{TALONX_PIV_LOCK_DIR or default}\*.lock` absence or an explicit `.release()`).
2. No exit/recovery task remains active (EOD reconciliation resolved, no
   `UNCONFIRMED_TIMEOUT` order outstanding in `lifecycle_state.json`).
3. Fresh broker/internal reconciliation is `PASS` (`PaperLifecycle.reconcile()["matched"] ==
   True` AND zero open broker orders/positions, confirmed AFTER the session, not reused from this
   task's own earlier read).

Pending or failed reconciliation means research **waits** — this is a hard gate, not a
recommendation.

## Existing development-data provenance (reused, not re-derived)

- **Development/discovery period**: `2025-08-15` through `2026-08-14` (established across Tasks
  7B/21/22/72O/74S — see `docs/research/TALONX_RESEARCH_LEDGER.md` line ~2203).
- **Holdout/OOS period**: `2026-08-17` onward — **this now includes essentially the entire recent
  period up to and including today (2026-08-27) and tomorrow's live session (2026-08-28)**. Any
  hypothesis batch must draw exclusively from the development window; today's/this week's/
  tomorrow's live data is holdout-protected by the SAME pre-existing boundary, not a new
  restriction invented by this task.
- **Canonical development dataset**: `data/historical_1m/task7b_alpaca_long_history/` (10-symbol:
  AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX — confirmed present, unchanged, via a
  read-only directory listing this task).

## Protected holdout boundaries (not accessed this task)

No file dated `2026-08-17` or later, and no live/rehearsal PAPER session output, may be used as
alpha-discovery input. The existing safeguards from Task 74S/75S (documented-provenance-only
universe/window selection, no post-result parameter changes) remain the governing methodology —
this plan does not relax them.

## Isolated research output location

Any future work follows the established `results/task<N><letter>_<slug>/` convention, force-added
(`git add -f`) since `/results/` is gitignored — matching every prior research task in this
branch's history. No new convention is proposed.

## Proposed bounded, preregistered hypothesis batch (PROPOSAL ONLY — not started, not run)

Given Task 74S's own finding (`NO_ELIGIBLE_LONG_SETUPS` across the full 10-symbol/~1-year
development window with the frozen long-only configuration) and Task 75S's confirmation that the
LOW_VOLATILITY/LOW_CONFLUENCE gates are correctly implemented (not defective), the next
scientifically honest step is NOT another parameter search on the same frozen configuration, but
one of:

- **Option A** (preferred): a preregistered, DOCUMENTED-PROVENANCE-ONLY re-examination of whether
  the 35-symbol operational universe (vs. the 10-symbol canonical baseline) changes the
  eligible-setup count, using the SAME frozen strategy, SAME development window, with the
  universe choice justified BEFORE observing any result (mirroring Task 74S's own protocol,
  which this branch's own evidence trail shows is the required discipline here).
- **Option B**: a preregistered audit of whether the strategy's OWN gate thresholds
  (confluence/RR/volatility) were originally calibrated against a different symbol set or era,
  with the audit's conclusion limited to "was this threshold ever empirically justified" — not a
  license to retune it.

Neither option is started, scheduled, or implied to be authorized by this document. A future task
would need to preregister the exact hypothesis, symbols, window, and success criteria BEFORE
running anything, per this branch's own established anti-p-hacking discipline (Tasks 74S/75S).

## Explicit non-scheduling

No research, full test suite, bulk download, or model installation is scheduled to run
automatically, overlapping, or immediately following Task 80's session. Resuming research is a
separate, explicit operator decision gated on the prerequisite checklist above.
