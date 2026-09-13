# Task 123 Part 2 — frozen protocol (before outcomes)

Written and committed BEFORE this task's diagnostic script was run
against real outcomes. `research/scripts/task123_overnight_diagnostic.py`
implements exactly what is specified here — the frozen constants live in
that file's own module-level definitions, cited by name below.

## Track A — daily-data association diagnostic

- **Static universe**: the 38 currently-**active** configured tickers
  (per `talonx_ops.watchlist_coverage.build_coverage_map()`'s own
  `status` field, snapshotted this task) with existing free daily-bar
  coverage — named explicitly in
  `ACTIVE_COVERED_38`. The 5 **paused** configured tickers (ASML, PATH,
  PLTR, RIG, SMCI) are excluded from this primary population — 3 of
  them (PLTR, RIG, SMCI) do have existing daily coverage but are
  excluded because they are paused, not because of a data gap; this
  exclusion is a labelled choice, not silently folded into "no
  coverage."
- **Primary dates**: each symbol's own full available history in its
  source file (2019-06-03 → 2026-08-14 for `task95g_broad_cross_sectional/_daily`;
  2019-01-02 → 2026-08-31 for `task107a_form4_feasibility/_prices`) —
  no window truncation.
- **Trigger**: `volume[S] >= 2.0x mean(volume[S-20..S-1])` — the 20
  sessions STRICTLY BEFORE S, excluding S's own volume from the
  baseline (`compute_track_a_symbol`'s `trailing_avg` computation).
- **Entry/exit reference and calendar alignment**: `S.close` →
  `next_XNYS_session.open`, where "next session" is
  `talonx_v2.calendar.next_session_strictly_after(S)` — the SAME frozen
  XNYS session-arithmetic module V2 uses elsewhere in this codebase.
  If the data's own next row does not match that calendar-computed
  date, the observation is EXCLUDED (`missing_next_session`), never
  paired with whatever the next available row happens to be.
- **Return definition**: `gross = open[next]/close[S] - 1`, computed
  from Alpaca SIP `adjustment=all` (split+dividend back-adjusted)
  daily bars — this is therefore a **total-return proxy** (dividends
  already embedded via back-adjustment), not a separately-added
  dividend adjustment, and not a raw/executable quote. No stock split
  affects either source directory differently — both use the identical
  `adjustment=all` convention (verified in `price_coverage.md`).
- **Corporate-action safeguard**: any observation with
  `abs(gross_return) > 0.50` (`EXTREME_RETURN_EXCLUSION_ABS`) is
  excluded and counted separately (`extreme_return_excluded`) — a
  conservative guard against the KNOWN, already-disclosed
  partial-adjustment-artifact class documented in
  `results/task107a_form4_feasibility/price_coverage.md` ("a few
  partial-adjustment single-day artifacts exist... Task 95G masked 49
  of 1.06M cells").
- **Cost convention**: `net = gross - 5.0bps/10000`
  (`COST_BPS_ROUND_TRIP`), applied exactly once — the same convention
  as every prior task in this research thread.
- **Practical materiality threshold**: **±10bps** on the INCREMENTAL
  (trigger-minus-control) mean, justified independently of any
  observed result: the modeled 5bps cost plus one additional assumed-
  friction unit of the same size (the identical doubling convention
  Task 121B used, for consistency, not chosen after seeing this
  task's own numbers). Sizing/notional conversion is explicitly NOT
  part of this materiality claim — this is a pure bps-return
  diagnostic; a dollar figure would only follow from a LATER, separate
  position-sizing decision and would not itself establish execution
  realism.
- **Control population**: the SAME 38 symbols' full unconditional
  overnight-return population (every eligible session, trigger or not)
  over the SAME dates — equal-weighted per EVENT (one session-night =
  one observation), not per symbol.
- **Uncertainty**: a **date-block bootstrap** (`_date_block_bootstrap`),
  5,000 reps, seed **123123**, 95% percentile CI — resamples DISTINCT
  TRADING DATES with replacement (not individual observations or
  issuers), computing the trigger-population mean AND the control-
  population mean from the SAME resampled date-multiset each
  replicate, then their difference — this preserves the joint
  trigger/control overlap and captures common cross-sectional
  market-shock correlation on shared dates, rather than treating
  observations (or issuers) as independent.
- **Sensitivities (exactly two, both exact, neither vague)**:
  1. A stricter trigger multiple, **2.5×** exactly (not "e.g. 3×") —
     `TRIGGER_MULTIPLE_SENSITIVITY`, computed on the SAME frozen
     population/window.
  2. Drop-top-1-issuer (by trigger-event count) — reported as a
     descriptive comparison of means, not a competing/independent
     confidence interval (correlated stocks are not treated as fully
     independent anywhere in this protocol).
- **Stopping rule**: run once over each symbol's full available
  history; no window extension regardless of result.

## Track B — actionable pre-close candidate

- **Universe**: the 12 configured, active, daily-covered tickers that
  ALSO have existing free 1-minute intraday coverage
  (`task93_canonical_v1`): AAPL, AMAT, AMD, AVGO, CSCO, GOOGL, INTC,
  MSFT, NVDA, PYPL, STX, TSLA.
- **Window**: `2025-01-24 → 2025-08-14` — the COMMON coverage across
  all 12 candidates (4 of the 12 have data only through this date; the
  other 8 extend further, to 2026-08-14, but using each symbol's own
  longer range would bias later months toward the 8 with more history —
  the common window is used for all 12, no cherry-picking).
- **Decision cutoff**: **15:50 ET (20:50 UTC)** — 10 minutes before the
  actual 16:00 ET / 21:00 UTC close. Chosen as a round, defensible
  pre-close cutoff with enough margin for a realistic decision process;
  not searched against alternatives.
- **Reference volume measure**: **same-time-of-day cumulative volume**
  — the sum of 1-minute bar volume from the regular session's own open
  (09:30 ET / 14:30 UTC) through the decision cutoff, TODAY, compared
  against the trailing 20-session average of the SAME same-time-of-day
  cumulative metric (each of the prior 20 sessions' own open-to-15:50
  cumulative volume) — explicitly NOT a prior-full-day average (which
  would compare a partial-day figure against a full-day baseline, a
  different and biased normalization). This choice is stated and
  justified before any outcome was computed.
- **Trigger**: the SAME 2.0× multiple as Track A (no re-tuning).
- **Alert/processing delay**: **2 minutes**, fixed
  (`ALERT_DELAY_MINUTES`) — representing a minimal realistic
  computation-and-order-submission latency; not searched against
  alternative delays.
- **Entry-price observation**: the 1-minute bar's close at
  **15:52 ET (20:52 UTC)** — decision cutoff + the fixed delay. Labelled
  a **REFERENCE FILL** throughout (an observed subsequent price, never
  claimed as an executable quote this task can guarantee).
- **Exit**: the next XNYS session's own regular-open 1-minute bar
  (same `next_session_strictly_after` calendar logic as Track A) —
  also a reference fill.
- **Costs**: the same 5bps round-trip convention, applied once.
- **Missing-data handling**: a session missing its own cutoff/entry bar,
  or a next session missing its own open bar, is EXCLUDED and counted
  separately by exact cause (`missing_entry_bar`,
  `missing_next_session`) — never substituted with a nearby bar.
- **Corporate actions**: `task93_canonical_v1` is UNADJUSTED
  (confirmed from its own manifest); the existing
  `data_quality_report.md` audit for this exact dataset already found
  **no stock splits** for any of its 35 symbols within this window
  ("none of the 35 split in 2025-01 → 2026-08") — cited, not
  re-derived. Dividends are NOT adjusted for (a raw price-return
  measure, distinct from Track A's total-return proxy) — disclosed as
  a genuine difference between the two tracks, not reconciled.
- **Stopping rule**: run once, this exact frozen contract, no search
  over cutoffs/delays/holding periods.

Both tracks were fully specified above BEFORE
`research/scripts/task123_overnight_diagnostic.py` was run against real
return outcomes (only the Task 122 trigger-frequency counts, and this
task's own pre-check unit tests on synthetic data, had been inspected
beforehand).
