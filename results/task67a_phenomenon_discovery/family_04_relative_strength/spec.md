# Family 4 -- Relative Strength vs SPY / Sector ETF -- Screening Spec

Task 67B Step 2. Stage 1 phenomenon-discovery screening, DEVELOPMENT data only
(35 symbols, 2026-05-15..2026-08-14, ~62-63 trading days -- the brief's nominal
figure is ~62; the actual unique-day count observed in the loaded DEVELOPMENT
bars, 63, is what the calibration/application split is computed from). Read-only,
exploratory -- NOT a trading engine, NOT a backtest, NOT strategy freezing.

Question: does stock-specific residual strength relative to market/sector predict
subsequent continuation? A naive `stock_return - SPY_return` ("raw RS") is
contaminated by beta: a high-beta stock looks artificially strong on raw RS during
any market rally, and that is not a stock-specific phenomenon. This family
separates the two via a causal, fail-closed beta adjustment (section A) and treats
the beta-adjusted residual, not raw RS, as the verdict-relevant effect (section B).

## A. Beta estimation (done ONCE, causally, fail-closed)

The sorted unique `trading_day` values present in the loaded DEVELOPMENT bars are
split in half by calendar day (`calibration_application_split`): the first
floor(n/2) days are the "calibration half", the remaining (>=) days are the
"application half" -- computed from the ACTUAL data, never a hardcoded date guess.
In the real run this produced **31 calibration days (2026-05-15..2026-06-30)** and
**32 application days (2026-07-01..2026-08-14)**.

For each of the 35 symbols, USING ONLY calibration-half 1-minute bars,
`beta_spy = Cov(stock_ret, spy_ret) / Var(spy_ret)` is estimated via `_compute_beta`
as an OLS slope on paired SAME-TIMESTAMP 1-minute returns (inner merge on
timestamp between the stock's own `_one_minute_returns` and SPY's). Return
definition: simple close-to-close pct return between two CONSECUTIVE same-day bars
whose gap is <= 5 minutes (`MAX_RETURN_GAP_MINUTES`) -- tolerates the occasional
missing 1-min bar without silently treating a multi-hour-gap move as a 1-minute
return. `beta_sector` is estimated identically against the symbol's mapped GICS
sector ETF, from `benchmark_inventory.json`'s `sector_etfs.mapping`
(`load_sector_mapping` reverses ETF->symbols into symbol->ETF).

**Fail-closed rule:** a symbol's beta is trusted only if its calibration-half
paired-observation count is `>= MIN_PAIRED_OBS_FOR_BETA = 2000` -- roughly 2
trading days of continuous 1-minute bars at this dataset's ~900 bars/session pace,
a low, explicitly-documented bar (not tuned to flatter any symbol). Below that,
`beta_spy`/`beta_sector` is `None` and the symbol is EXCLUDED from the
beta-adjusted analysis (section B) -- never defaulted to beta=1 or beta=0. In the
real run, **all 35 symbols cleared both thresholds (0 failed closed)** -- observed
`beta_spy` ranged [-0.183, 3.346] (median 0.891), `beta_sector` ranged
[0.112, 1.715] (median 0.910). See `summary.json`'s `beta_estimates` for the full
per-symbol table.

**Causal isolation:** ALL Family 4 candidate events (all 3 definitions) are
restricted to the APPLICATION HALF only (`build_rs_candidates`'s `app_mask`), so
beta is never estimated using data at or after the event it is applied to.
`tests/test_task67a_family04_relative_strength.py::test_beta_never_uses_
application_half_data` is a dedicated regression test: two synthetic datasets
share an identical calibration half but have WILDLY different application halves
(stock = -1.0x SPY vs stock = +7.0x SPY there); both recover the SAME calibration
beta (2.0x, bit-identical between the two runs), proving application-half data is
never touched.

## B. Three RS definitions + beta-adjusted residual

Definitions vary only the trailing-return window used for the RS SIGNAL itself
(the beta methodology above is one fixed approach shared across all three):

### `rs_trailing_30m` / `rs_trailing_60m` / `rs_trailing_90m`
RAW RS = causal {30,60,90}m trailing stock return (`causal_trailing_return`) minus
causal {30,60,90}m trailing SPY return, where the SPY (and sector ETF) trailing
return is looked up via `_causal_benchmark_lookup` -- a cross-table generalization
of `causal_price_at_offset`'s same-day, per-symbol, searchsorted lookback logic,
needed because the price SOURCE here is a benchmark's own single-symbol bar table,
distinct from the 35-symbol `bars_feat` QUERY frame.

Event condition: RAW RS in the top/bottom `RS_TAIL_QUANTILE = 0.10` (a two-sided
global-decile extremity threshold) of the POOLED APPLICATION-HALF RAW RS values
for that definition (computed once per definition over the same population the
candidate events are drawn from, never leaking calibration-half values into the
threshold), at a bar at/after 14:00 UTC (`POST_OPENING_RANGE_UTC_HOUR`, excludes
the first 30 minutes of RTH -- ORPB territory), with >=15 minutes of same-day room
before RTH close. Direction = sign(RAW RS) -- does strong (or weak) relative
strength continue.

## De-duplication

`research_stats.dedup_events`, `group_keys=["symbol"]`, `keep="first"`.
`min_gap_minutes` = window_minutes / 2 (15 / 30 / 45 for the 30/60/90m windows,
minimum floor 10) -- shorter defining windows get shorter re-trigger gaps, mirroring
Family 3's window-scaled dedup precedent. Both RAW and DEDUPLICATED counts are
reported.

## Standard pipeline (raw RS matched-control numbers)

Each definition's deduplicated candidate-event set runs through the SAME shared
`run_family_definition` pipeline as Families 1-3 (matched-control construction via
`sample_control_candidates` + `matched_control_sample`, stratified by
`["symbol", "time_of_day_bucket", "vol_bucket"]`, clustered-by-symbol bootstrap 95%
CI, concentration, effect-surface stability, economic classification, data
sufficiency, verdict). This produces the RAW RS matched-control excess numbers
that populate `events.csv` / `horizon_metrics.csv` / `matched_control_metrics.csv`
/ `mfe_mae.csv` and are reported in `summary.md`/`summary.json` labeled "raw,
before beta adjustment" -- NOT the family's verdict basis.

## Family-4-specific: beta-adjusted residual (`compute_beta_adjusted_metrics`)

For the SAME deduplicated event set, restricted to symbols with a trustworthy
`beta_spy` AND `beta_sector` (fail-closed exclusion of the rest -- in the real run
this excluded 0 symbols, so all deduplicated events were used), computes per event
and horizon (15/30/60/120m):
  - `raw_forward_pct`: the event's own direction-adjusted forward return (from the
    standard pipeline's `horizon_metrics` -- NOT matched-control excess).
  - `spy_forward_pct` / `sector_forward_pct`: SPY's / the sector ETF's own forward
    return over the same horizon window from the event's timestamp
    (`forward_return_horizons` applied to the benchmark's own bars), direction-sign-
    adjusted the same way `compute_event_horizon_and_mfe_mae` adjusts (multiplied
    by the event's own direction sign).
  - `spy_adjusted_forward_pct = raw_forward_pct - beta_spy * spy_forward_pct`
  - `sector_adjusted_forward_pct = raw_forward_pct - beta_sector * sector_forward_pct`

`bootstrap_ci_clustered` (grouped by symbol) is run separately on all three series
at every horizon (`bootstrap_beta_adjusted`), with seeds
`DEFAULT_SEED + FAMILY_SEED_OFFSET(400) + BETA_BOOTSTRAP_SEED_OFFSET(40_000) +
definition_index*1000 + {0/10_000/20_000 per metric} + horizon_minutes` -- kept
far away from the standard pipeline's own per-horizon excess-bootstrap seeds so no
two independent bootstraps in this script share a seed.

`classify_economic_magnitude` is applied to the SPY-adjusted mean at the primary
60m horizon and the standard pipeline's `mfe_pct_median` (reused as a documented
proxy for a hypothetical perfect-exit upper bound -- it describes the event
distribution, not the beta-adjusted return metric specifically; no better
MFE/MAE reconstruction exists for a "beta-adjusted price path" without
re-simulating one, which is out of scope). This becomes the family's REPORTED
economic classification.

## Verdict (beta-adjusted basis)

A `VerdictInputs` is constructed manually per definition: `matched_control_
support`, `adequate_event_count`, `temporal_breadth`, `symbol_breadth`,
`stable_effect_surface`, `asymmetric_mfe_mae`, `concentration_low`, and
`data_sufficiency` are REUSED from the standard pipeline's own result (a
documented simplification -- those describe the EVENT distribution, not the
specific return metric). `coherent_direction`, `nontrivial_economic_scale`, and
`excess_ci_excludes_zero` are instead computed from the SPY-ADJUSTED bootstrap/
economic-classification results, not the raw ones. `determine_verdict` is called
on this beta-adjusted `VerdictInputs`; its output is THE definition's reported
verdict. Where raw RS looks economically meaningful with a CI excluding zero but
the SPY-adjusted residual's CI includes zero or its classification drops to
ECONOMICALLY_TOO_SMALL, `summary.md` states explicitly for that definition:
"likely factor/beta exposure, not a stock-specific phenomenon."

## Economic friction assumption

`screening_framework.ONE_WAY_FRICTION_BPS = 5.0`,
`ROUND_TRIP_FRICTION_BPS = 10.0` (module constants, unchanged). Same
`classify_economic_magnitude` thresholds as Families 1-3.

## Seeds

Standard pipeline: `DEFAULT_SEED = 670067` + `FAMILY_SEED_OFFSET = 400` (family 4)
+ definition index (0/1/2), plus the per-horizon excess bootstrap adds the
horizon's minute count -- identical convention to Families 1-3. Beta-adjusted
bootstraps: see the "Family-4-specific" section above. Exact per-definition seeds
recorded in `definitions.json` / `summary.json`.
