# Task 118F Part 4 — volatility-return exploratory test (2026-09-11)

**Decision: EXPLORATORY_ASSOCIATION_SUPPORTS_ONE_FURTHER_TEST.** All
results below are exploratory (already-inspected A/B/C history, per
Task 118D/E) — none is a fresh holdout, and none is presented as one.

## Predeclared protocol (see `volatility_return_test.py` docstring for the
byte-exact version, written before any result was computed)

- **Feature**: 20-trading-day pre-entry realized volatility, annualized
  %, computed **per trade** (each trade's own entry date, not a shared
  first-entry-date per issuer as in Task 118E's composition check).
- **Estimand**: OLS slope of net trade return (20bps convention) on the
  volatility feature, treated **continuously** — no binning, no cutoff
  search.
- **Dependence**: issuer-block bootstrap (primary), month-of-entry
  time-block bootstrap (sensitivity) — 5,000 reps, seed 118118, same
  family as every other Task 118D/E/F resample.
- **Populations**: A and B analyzed **separately** as primary; pooled
  reported only as an explicitly-labelled secondary check, never
  interpreted as a within-population effect.
- **Sensitivity**: drop-MSTR (concentration check, full A retained as
  primary).
- **Missing data**: 0 trades excluded in A or B (all issuers had ≥20
  trading days of prior history).

## Results

| population | n trades | n issuer blocks | slope (net return per +1pp vol) | 95% CI (issuer-block) | 95% CI (month-block) |
|---|---:|---:|---:|---|---|
| **A** (primary) | 10 | 6 | **−0.001733** | **[−0.00349, −0.000246]** | **[−0.00325, −0.000296]** |
| **B** (primary) | 147 | 101 | +0.000256 | [−0.000139, +0.000810] | [−0.000206, +0.000719] |
| pooled (secondary only) | 157 | 107 | +0.0000333 | [−0.000509, +0.000577] | [−0.000399, +0.000448] |
| A, drop-MSTR (sensitivity) | 6 | 5 | −0.000658 | [−0.001325, +0.000157] | [−0.001083, +0.000304] |

## Interpretation

**Within Population A specifically**, there is a **negative association
between pre-entry volatility and net trade return that excludes zero
under both dependence assumptions** (issuer-block and month-of-entry
time-block agree on direction and on excluding zero) — a real, if
small-sample, finding in the data as collected. Over A's observed
volatility range (≈15%–129% annualized), the slope implies roughly a
20-percentage-point swing in net return across that range — consistent
with the low-volatility winners (ADC) and high-volatility losers
(MSTR, ACHR) already documented in Task 118/118E.

**Population B shows no such relationship** — its slope is small,
positive in sign, and its CI includes zero under both methods. The
**pooled** fit also shows no relationship (correctly not conflated with
either population's own result — this is exactly why A and B are reported
separately as primary).

**Concentration check**: dropping MSTR (A's largest single contributor)
**removes statistical significance** — the CI now includes zero under
both methods, though the **point estimate keeps the same negative sign**
and similar order of magnitude. **Direction is stable across every
sensitivity check performed (issuer-block, time-block, drop-MSTR); the
statistical significance of A's own result is not stable to MSTR's
removal.** Both facts are reported together, not one without the other.

## Explicitly not claimed

This is a **descriptive association**, not a causal claim — no mechanism
is asserted beyond the plausible rationale already stated in Task 118E
(a fixed, non-volatility-scaled hold/cost structure could plausibly
realize more of a high-volatility name's noise within the hold window).
No volatility filter is added to production. MSTR is not removed from
any primary result — it remains in every primary-population figure
throughout this report and every prior Task 118 report.

## Research decision: EXPLORATORY_ASSOCIATION_SUPPORTS_ONE_FURTHER_TEST

**Evidence, in plain language**: within the 39-name scope's own 10
trades, higher-volatility entries have historically done worse — this
holds up under two different ways of accounting for repeated issuers and
time clustering, which is a real (if statistically fragile at N=10)
signal, not noise from a single arbitrary resampling choice. But it is
substantially carried by one issuer (MSTR), so it should not be treated
as an established, broad pattern across all six issuers.

**What the further test provides that this analysis does not**: this
entire analysis reuses the SAME already-inspected 2024–2026 trades used
throughout Task 118. It cannot, by construction, tell us whether the
association will hold going forward. The further test — already specified
in Task 118E's `ONE_TESTABLE_HYPOTHESIS`, **unchanged here, now with this
report's stronger evidentiary basis** — requires genuinely new information:
**forward, live 39-name-scope entries** (not yet observed), recording the
same pre-entry volatility feature at real entry time and testing the
same within-scope relationship once N≥10 new live entries accumulate.
**Confirmation data source: future live trading only** — no re-slice of
the already-used 2024–2026 history is treated as a fresh test.

## Evidence

`results/task118_profitability/volatility_return_test.py` (checked in,
predeclared protocol in its own docstring),
`reconciliation/volatility_return_test.json` (full numeric results,
checked in), `reconciliation/volatility_return_trades.csv` (per-trade
feature/return pairs, sanitized, checked in).
