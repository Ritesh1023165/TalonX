# Task 125 — frozen extension protocol (before any new return is computed)

Written and committed BEFORE `research/scripts/task125_overnight_evaluation.py`
is run against any real return outcome. Only data-availability probes
(feed identity, symbol coverage, listing windows — no return, no
trigger, no P&L) were inspected before this freeze; they are cited
below as the evidence basis for the choices made, exactly as Task 123's
own frozen protocol cited Task 122's trigger-frequency counts.

## What is retained from Task 123 Track B, unchanged

- **Decision cutoff**: 15:50 ET (20:50 UTC).
- **Reference volume measure**: same-time-of-day cumulative volume,
  regular-session open (09:30 ET) through the cutoff, vs. the trailing
  20-session average of the SAME same-time-of-day metric.
- **Trigger threshold**: 2.0× (`TRIGGER_MULTIPLE_PRIMARY`) — the only
  threshold Track B was ever run at; no sensitivity variant was
  predeclared for Track B in Task 123 (only Track A had two
  sensitivities — see `TASK123_FROZEN_PROTOCOL.md`). None is added
  here either: Task 125 extends Track B's DATA, not its analytical
  surface.
- **Alert/processing delay**: 2 minutes, fixed.
- **Entry reference price**: the 1-min bar close at 15:52 ET
  (decision cutoff + delay) — a reference fill, not a claimed
  executable quote.
- **Exit reference price**: the next XNYS session's own regular-open
  1-min bar, via `talonx_v2.calendar.next_session_strictly_after` —
  never "the next available row."
- **Cost convention**: 5.0bps round-trip, applied once
  (`COST_BPS_ROUND_TRIP`).
- **Materiality rule**: ±10bps on the incremental (trigger-minus-
  control) mean (`MATERIALITY_BAND_BPS`), justified independently of
  sizing (5bps modeled cost + one assumed-friction unit, the same
  doubling convention as every prior task in this thread).
- **Uncertainty method**: date-block bootstrap with joint trigger/
  control resampling from the same resampled date-multiset, 5,000
  reps, seed **123123** — the SAME seed as Task 123, because this is
  the same frozen procedure applied to new data, not a new randomized
  choice.
- **Extreme-return guard**: `abs(gross_return) > 0.50` excluded and
  counted (`EXTREME_RETURN_EXCLUSION_ABS`).
- Not substituted: final daily volume, yesterday's volume, a different
  cutoff, a different delay, or a different holding period. None of
  these were touched.

## 1. Exact ticker list, active/paused snapshot, and source

- **Original 12-symbol cohort** (Task 123 Track B's own universe,
  unchanged): AAPL, AMAT, AMD, AVGO, CSCO, GOOGL, INTC, MSFT, NVDA,
  PYPL, STX, TSLA.
- **Candidate added cohort**: the 5 active-but-locally-uncovered names
  Task 124 identified — BABA, BLSH, SHOP, SKHY, SPCX. **Resolved to 3
  BEFORE any return was computed**, from coverage evidence alone
  (`results/task125_intraday_extension/feed_provenance_probe.json`,
  probe `new_symbol_availability` + two listing-window checks):
  - **BABA, SHOP, SPCX** — full daily-bar coverage across the entire
    target window (656/656 trading days, 2023-01-03→2025-08-14 SIP
    daily bars) — **included** in the added cohort.
  - **SKHY** — first available Alpaca bar is **2026-07-10**, entirely
    AFTER the target window ends (2025-08-14). This is a genuinely
    unavailable history for this study, not a data-quality defect:
    SK Hynix's US-tradable listing under this ticker post-dates the
    entire evaluation window. **Excluded**, with the exact reason
    recorded, not silently dropped.
  - **BLSH** — first available Alpaca bar is **2025-08-13**, one
    trading day before the window's own end and with zero prior
    trailing history — cannot supply even one eligible trigger under
    the frozen 20-session lookback. **Excluded**, same treatment.
  - This is a coverage-based exclusion decided from listing dates
    alone, before any trigger or return was computed — not a
    performance-based cohort selection.
- **Status snapshot**: all 15 named symbols (12 original + 3 added)
  are **active** per `talonx_ops.watchlist_coverage.build_coverage_map()`,
  snapshotted 2026-09-13 (same snapshot already recorded in Task 124's
  coverage manifest) — current watchlist membership is used only to
  scope which symbols are worth checking, not treated as a historical
  point-in-time membership claim.
- **Source**: freshly acquired via Alpaca's `/v2/stocks/{symbol}/bars`
  endpoint, `feed=sip`, `adjustment=raw`, `timeframe=1Min` — NOT reused
  from `task93_alpha_foundation/_canonical_data` (see §2).

## 2. Exact start/end dates and required pre-roll

- **Acquisition range**: **2022-12-01 → 2025-08-14**. The 2022-12-01
  start provides a pre-roll buffer of ~22 trading sessions before
  2023-01-01, comfortably covering the 20-session trailing-volume
  lookback so real evaluation-eligible dates begin near the start of
  January 2023 rather than losing a full month to warmup.
- **Evaluation window (post-warmup)**: effectively **2023-01-01 →
  2025-08-14** once the 20-session lookback is satisfied — the exact
  first eligible date per symbol is reported in the eligibility funnel
  (§4 of the results document), not asserted here.
- **Common endpoint**: **2025-08-14**, chosen because it is the
  documented end of Task 123 Track B's own study window (the common
  coverage boundary across the original 12 symbols) — resolved from
  that existing frozen document, not chosen after inspecting any new
  return. Extending PAST this date was not pursued (Task 124's own
  concrete acquisition spec named an extension backward to
  2023-01-01, not forward).
- Per the research journal (Task 123's `outcomes_already_inspected`
  entry in Task 124's own coverage manifest): the 2023-01-01→
  2025-01-23 portion of this window (the part before Task 123 Track
  B's existing 2025-01-24 start) is **unused for this specific
  hypothesis** — no trigger, return, or outcome from this exact
  mechanism has ever been computed over it in this research program.
  This is stated precisely as "unused for this hypothesis," NOT as a
  formally independent, pre-registered holdout — the daily-bar
  association study (Task 123 Track A) and other price/volume alpha
  work (Tasks 93–95G) have already examined overlapping calendar
  periods and symbols under DIFFERENT hypotheses, so this is not a
  claim of genuinely fresh, never-analyzed market history in any
  absolute sense.

## 3. Feed, adjustment mode, and corporate-action policy

- **Feed identity of the legacy dataset, resolved from contemporaneous
  acquisition code, not inferred from prices/row counts alone**: all
  three of `task93_canonical_v1`'s declared sources
  (`task63_orpb_v1_validation`, `task61r_fprc_v1_validation`,
  `task7b_alpaca_long_history`) route through the same shared
  `scripts/download_historical_1m.py::fetch_alpaca`, whose Alpaca
  request parameters never include a `feed` key at all — confirmed by
  direct read of `task63_download_alpaca.py`,
  `task61r_download_alpaca.py`, and `task7b_alpaca_long_history/
  download_summary.json`'s own `"provider": "alpaca"` field format
  (identical to `download_historical_1m.py`'s summary schema).
  A confirmatory live probe (AAPL, 2025-02-05 — the same date/symbol
  used in Task 124's own already-covered-period probe) then issued the
  EXACT omitted-feed request the legacy code made, alongside explicit
  `feed=sip` and `feed=iex` requests: the omitted-feed response is
  **bar-for-bar identical** to the explicit-SIP response (841 bars,
  identical SHA-256 fingerprint over every `(t,o,h,l,c,v)` tuple) and
  differs from IEX (388 bars, different fingerprint). **Conclusion:
  `task93_canonical_v1` is SIP data** — this account's default feed
  (when omitted) already resolves to SIP, not IEX. This reverses
  Task 124's own open question; full evidence in
  `results/task125_intraday_extension/feed_provenance_probe.json`.
- **Consequence**: because the legacy dataset and this task's fresh
  acquisition are now both confirmed SIP, they are feed-consistent.
  This task nonetheless does NOT concatenate them file-for-file (see
  §Acquisition below) — it acquires one clean, independently-verified,
  contiguous SIP series for the full 2022-12-01→2025-08-14 range and
  uses that alone for every cohort, including the sub-window that
  overlaps the legacy file's own coverage. The legacy
  `task93_canonical_v1` files are left untouched. Because both are now
  known to be the SAME feed, an EXACT numerical match between Cohort D
  (§5 of the results document) and Task 123's original Track B numbers
  IS a reasonable expectation, stated here BEFORE running Cohort D —
  not fabricated after the fact — subject only to routine
  provider-response non-determinism (e.g. a bar Alpaca's backend has
  since revised) if any is found.
- **Adjustment mode**: `adjustment=raw` — matches Track B's existing
  UNADJUSTED convention (a raw price-return measure, not Track A's
  total-return proxy; this distinction is unchanged and not
  reconciled here).
- **Corporate-action policy**: RAW/unadjusted bars mean a stock split
  would appear as a large single-bar discontinuity. The SAME
  `EXTREME_RETURN_EXCLUSION_ABS=0.50` guard already frozen in Task 123
  is the sole corporate-action safeguard — any observation whose gross
  overnight reference return exceeds it is excluded and counted
  (`extreme_return_excluded`), never silently kept or replaced with an
  adjusted price. No known split events for the 3 added symbols were
  looked up in advance (that would risk outcome-adjacent searching);
  the exclusion guard is the predeclared, mechanical handling for
  whatever is found.
- **Volume comparability across splits**: because a raw price/volume
  series is used, a split would also distort the same-time-of-day
  cumulative-volume trigger for one 20-session window surrounding it.
  No manual correction is applied — this is a known, disclosed
  limitation of the raw-price convention (same limitation Task 123
  already carried for the original 12 symbols), not a new gap
  introduced by the extension.

## 4. Missing-data and early-close treatment

- Unchanged from Task 123's own `compute_track_b_symbol`: a session
  missing its own cutoff bar (20:50 UTC), entry bar (20:52 UTC), or a
  next session missing its own regular-open bar (14:30 UTC) is
  EXCLUDED and counted by exact cause — never forward-filled or
  substituted with a nearby bar.
- **Early-close sessions**: not separately special-cased. Because the
  contract keys off exact minute-of-day timestamps (20:50/20:52 UTC
  for the decision/entry, 14:30 UTC for the next-session open), an
  early-close session whose regular session ends before 20:50 UTC
  will simply be missing its cutoff/entry bars and fall into the
  existing `missing_cutoff_bar`/`missing_entry_bar` exclusion buckets
  automatically — not fabricated, not misclassified as a normal
  session. This is flagged explicitly here as a known mechanical
  consequence, not silently discovered later.
- **No pre-listing fabricated histories**: BABA/SHOP/SPCX all have
  full daily coverage across the acquisition window (confirmed §1);
  no synthetic or backfilled bars are created for any date before a
  symbol's actual first available bar.

## 5. Primary estimand, control construction, uncertainty method, materiality rule

Unchanged from Task 123 Track B (see "What is retained," above).
Restated for this document's completeness: the primary estimand is
the incremental (trigger-minus-control) mean net reference-fill
overnight return; the control population is the SAME cohort's full
unconditional eligible-observation population over the SAME window;
uncertainty is the date-block joint-resampling bootstrap (5,000 reps,
seed 123123); materiality is ±10bps on the incremental estimate.

## 6. Exact decision criteria

**Statistical** (applied to each cohort's incremental estimate and its
95% CI):
- `EVIDENCE_SUPPORTS_PREDECLARED_EFFECT` — CI excludes zero, entirely
  on the positive side, AND the point estimate clears the ±10bps
  materiality band.
- `EVIDENCE_AGAINST_PREDECLARED_EFFECT` — CI excludes zero, entirely
  on the negative side.
- `INCONCLUSIVE` — CI includes zero, OR the CI excludes zero but the
  point estimate does not clear the materiality band.

**Product** (applied to the PRIMARY cohort — Cohort A, the original
12-symbol universe on the expanded window, per the frozen population
hierarchy in §5 of the results document; Cohort C is explicitly
secondary):
- `ADVANCE_TO_FURTHER_VALIDATION` — statistical verdict
  `EVIDENCE_SUPPORTS_PREDECLARED_EFFECT` on Cohort A AND the absolute
  net trigger return (not just the incremental) is positive and
  economically non-trivial (exceeds the same materiality band on an
  absolute basis) — a positive incremental estimate riding on a
  negative absolute return is NOT sufficient, per this task's own
  explicit instruction.
- `DO_NOT_ADVANCE` — statistical verdict `EVIDENCE_AGAINST_PREDECLARED_EFFECT`
  on Cohort A, OR `EVIDENCE_SUPPORTS_PREDECLARED_EFFECT` without a
  positive economically-credible absolute net return.
- `EVALUATION_BLOCKED_BY_DATA_QUALITY` — used instead of either of the
  above only if the eligibility funnel or corporate-action guard
  reveals a defect (not merely a small sample) that prevents a
  trustworthy estimate on Cohort A specifically.

These criteria are applied without rewriting them after results are
seen — see the results document's own explicit citation of this
section.

## 7. Prior data exposure and research limitations

- The 12 original symbols' 2025-01-24→2025-08-14 sub-window has
  already been fully analyzed for this exact hypothesis (Task 123);
  Cohort D exists specifically to isolate and disclose that overlap,
  not to hide it inside a larger blended number.
- The 3 added symbols (BABA, SHOP, SPCX) have NOT been evaluated for
  this specific overnight-attention/pre-close mechanism before —
  BABA/SHOP appeared only in Task 122's daily-frequency-only trigger
  count and Task 123 Track A's daily association study (a DIFFERENT
  hypothesis, non-actionable by construction); SPCX has never been
  evaluated for any return in this research program (only its raw
  data-thinness was probed in Task 124).
- All 15 symbols' DAILY bars (not this task's minute bars) have
  contributed to earlier broad cross-sectional alpha work (Tasks 93,
  95E, 95G) under materially different hypotheses (momentum,
  cross-sectional ranking) — named for transparency, not because it
  invalidates this specific test.
- This remains an EXPLORATORY, single frozen run, not a
  train/confirmation split — consistent with this program's standing
  convention that a single frozen run is not automatically
  "confirmatory" merely because the underlying calendar dates are new.

Both cohorts, the full symbol/date/feed specification, and the
decision criteria above were fully fixed BEFORE
`research/scripts/task125_overnight_evaluation.py` was run against any
real return outcome — only the data-availability probes cited in §1–3
(no trigger, no return, no P&L) were inspected beforehand.
