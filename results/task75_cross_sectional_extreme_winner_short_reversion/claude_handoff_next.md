# Claude Handoff -- after Task75A

## Immediate next priority

**Task75B is BLOCKED, not ready to run.** Before ANY validation outcome
can be computed:

1. **Resolve the corporate-action provenance problem**
   (`corporate_action_policy.json`). This repo's Alpaca downloader
   requests `adjustment=raw` for every historical bar -- confirmed by
   direct source inspection. At least two well-known public 10:1 stock
   splits (NVDA ~2024-06-10, AVGO ~2024-07-15) fall inside the reserved
   VALIDATION window (2024-06-01..09-02). A raw price series would show
   a catastrophic artificial discontinuity at each split date, which
   would corrupt both the 3-day cross-sectional ranking feature and any
   position's P&L if it spans the split. Fix options:
   - Re-download the validation and replication windows with
     `adjustment=split` (or `all`) instead of `raw`, OR
   - Obtain a verified corporate-action event table and explicitly
     exclude/adjust the affected symbol/date windows.
   Do NOT validate against the current raw dataset under any
   circumstance -- this is a hard blocker, not a soft caveat.

2. **Build a Task75B-specific holdout guard** (a `LockedRangeGuard`
   following `research/task72_residual_momentum/holdout_guard.py`'s
   pattern), constructed with EXACTLY the two reserved ranges
   (`2024-06-01..2024-09-02` validation, `2024-10-21..2024-12-20`
   replication) -- not built in Task75A on purpose, since Task75A must
   not prepare to touch 2024 data at all.

3. **Reverify the fingerprint** (`candidate_fingerprint.json`) before
   trusting anything -- recompute
   `research.task75_v1.fingerprint.compute_fingerprint()` and
   `compute_contract_only_fingerprint()` and confirm EXACT equality
   with the recorded values
   (`08930fb2...` and `677adccd...` respectively) before running
   `research/task75_v1/strategy.py::evaluate()` against real data.

4. **Apply `validation_protocol.json`'s 17 criteria mechanically, once.**
   The primary pass/fail gate is net expectancy at the 25bps all-in
   cost (not 10bps) -- this is a SHORT-only strategy with real,
   currently-unmodeled borrow/dividend costs, and 10bps was explicitly
   judged insufficient for a short. Task74B's own `net@10bps >= +0.15%`
   bar is preserved as an additional mandatory floor, not replaced.

5. **Do not loosen any criterion after seeing numbers**, and do not
   attempt replication unless classification is exactly
   `VALIDATION_PASS`.

## If you're asked "why not just run validation anyway, the split issue probably doesn't affect much"

Don't. Two known splits inside the exact validation window for this
exact universe is not a marginal edge case -- NVDA and AVGO are
significant weight in this 35-symbol mega-cap universe, and an
unadjusted 90% single-bar price drop at a split date would either (a)
generate a spurious extreme cross-sectional rank observation exactly
the kind of thing this strategy is designed to trade on, contaminating
the signal with a data artifact rather than a real price move, or (b)
catastrophically corrupt the P&L of any position spanning the split
date. This is exactly the kind of avoidable data-integrity failure the
whole research program has structured itself to catch before it reaches
a holdout, not after.

## If you're asked about the effective-search-count caveat

It's real and disclosed (`effective_search_accounting.json`) -- the
candidate emerged from comparing 40 direction-level outcomes, not 20
pre-declared hypothesis cells. This doesn't invalidate the nomination
(large margin, genuine 6-cell parameter plateau, both cluster CIs
excluding zero at the anchor cell), but it is why the validation
protocol was NOT loosened and instead holds Task74B's bar as a floor
while adding new, stricter overlapping-dependence checks.

## Files worth reading first

- `task75a_summary.md` (this task's full narrative)
- `corporate_action_policy.md` (the blocker)
- `validation_protocol.md` (the pre-registered criteria)
- `candidate_fingerprint.json` (verify before running anything)
