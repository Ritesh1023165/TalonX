# Task 127 Part 6/7 — 52-week-high long-term evaluation, results and decision

> **Correction (Task 128, 2026-09-13)** — applied to stored artifacts
> only; Task 127's selection-strategy computation was NOT rerun.
>
> - The 52-week-high tercile contract's **`DO_NOT_ADVANCE`** verdict
>   stands unchanged.
> - **"The added selection complexity is not justified; simply holding
>   the eligible universe outperformed it"** overstated what this
>   evaluation showed. Corrected: the tercile selection strategy **did
>   not demonstrate added value in this evaluation** relative to
>   Benchmark B1 — the incremental 95% CI includes zero, so this is an
>   absence of supporting evidence, not a proof that selection has zero
>   or negative value.
> - **"12 genuinely non-overlapping 6-month macro-blocks... 12 blocks
>   is a small number of truly independent periods"** overstated the
>   bootstrap's guarantee. Non-overlapping IN TIME is not the same as
>   statistically independent — adjacent blocks can still share broad
>   market-regime persistence, correlated issuer composition (the same
>   38-name universe), and macro autocorrelation the block construction
>   does not remove. The block bootstrap reduces, but does not prove
>   away, dependence; "12 non-overlapping blocks" is the accurate
>   description, not "12 independent observations."
> - **"Attributable to broad market beta"** overstated a correlational
>   observation as a proven causal decomposition. No factor regression
>   or beta estimation was performed. Corrected: both Strategy A's and
>   Benchmark B1's strongly positive absolute returns are **consistent
>   with** broad market exposure during a strong secular bull run (SPY
>   +242.68% over the same span) — this is circumstantial, not a
>   quantified beta attribution.
> - **SPY's full-period (2019-01-02→2026-08-31) total return of
>   +242.68% and the strategy/benchmark's PER-6-MONTH-COHORT average
>   returns are not directly comparable metrics** — one is a single
>   compounded figure over ~7.5 years, the others are uncompounded
>   arithmetic means across 68 individual 6-month windows. The original
>   text's juxtaposition of these two numbers in one paragraph, even
>   with the utilization caveat noted, risked reading as a
>   like-for-like magnitude comparison. See
>   `docs/research/TASK128_BASELINE_CONTRACT_AND_ACCOUNTING.md` for the
>   corrected, genuinely comparable chronological-portfolio comparison
>   (same starting capital, same dates, both marked daily).
> - **The reported +13.70% (Benchmark B1) is an ARITHMETIC MEAN OF 68
>   INDIVIDUAL 6-MONTH COHORT RETURNS** (`np.mean(net)` over
>   `cohort_gross_net_return` outputs) — it is explicitly NOT a
>   chronological portfolio return. `run_chronological_portfolio` was
>   only ever invoked for Strategy A in the original script; Benchmark
>   B1's own chronological portfolio was never built. Task 128
>   addresses this gap directly by reusing the existing (generic,
>   already-parameterized) `run_chronological_portfolio` function for
>   Benchmark B1 as well — see `TASK128_BASELINE_CONTRACT_AND_ACCOUNTING.md`.
>
> None of the above changes the 52-week-high tercile contract's
> `DO_NOT_ADVANCE` product verdict or its `INCONCLUSIVE` statistical
> verdict — both stand as originally reported.

Runs `research/scripts/task127_52wk_high_evaluation.py` exactly ONCE,
implementing the contract frozen in
`docs/research/TASK127_FROZEN_LONG_TERM_PROTOCOL.md` before any return
was inspected. Full machine-readable output:
`results/task127_52wk_high_evaluation/task127_evaluation_results.json`
(copied to `docs/research/evidence/task127/`); realized trade log in
`portfolio_a_realized_trades.json`.

## Eligible dates, issuers, and the selection/entry/exit funnel

- **Data window**: 2019-01-02 → 2026-08-31 (union of the two daily
  directories' coverage for the 38-symbol universe).
- **92 monthly formation dates** evaluated.
- **18 formation months skipped** — insufficient eligible population
  (< 15 symbols with ≥252 trading days of their own history and price
  ≥ $5) — this is the expected warm-up period at the start of the
  window (D1's data starts 2019-06-03, so the first ~13 months have too
  few symbols with a full trailing year).
- **68 REALIZED cohorts** (complete 6-month forward window available)
  for both Strategy A (tercile selection) and Benchmark B1 (eligible-
  universe equal-weight) — the same 68 formation dates, by construction
  (both use the identical eligibility gate; only the SELECTION differs).
- **6 PENDING cohorts** — formed but their 6-month forward window is
  not yet complete within the available data (the most recent ~6
  formation months) — excluded from the primary estimand, not silently
  dropped.
- **37 distinct issuers** ever selected by Strategy A (of 38 possible);
  38 distinct issuers in Benchmark B1 (all eligible names appear, by
  construction, at some point).
- **0 formations lost to missing entry/exit data** in the realized set
  — this configured-universe daily panel has no gaps for the 38 active
  names over this window (consistent with Task 123/125's own findings
  for the same data).

## Selection, entries, exits, open positions (chronological portfolio, base 5bps cost)

- Ending cash / marked equity: **$222,980.46** (0 open positions at the
  end of the tracked window — the portfolio naturally winds down
  because no further cohorts can be FORMED within the available data's
  final ~6 months, not because of any error).
- 68 realized round-trip trades (cohort entry→exit pairs).
- **Capital utilization**: mean 4.43 of 6 slots filled per tracked
  month (≈74%), ranging from 0 (during the ~13-month warm-up and the
  final wind-down) to the full 6/6 once ramped. **This matters for the
  SPY comparison below — the chronological strategy portfolio is NOT
  fully invested throughout, unlike a SPY buy-and-hold; the two ending-
  equity figures are not a strictly apples-to-apples comparison.** The
  paired incremental-vs-Benchmark-B1 comparison (identical eligibility
  gate and slot/utilization treatment on both sides) is the primary,
  apples-to-apples estimand — not the SPY comparison.
- **Marked-equity max drawdown**: **−13.43%** (computed from the actual
  monthly marked equity curve, not from cash alone or summed trade
  returns).

## Absolute economics

| | Strategy A (tercile) | Benchmark B1 (eligible universe, no selection) |
|---|---:|---:|
| Gross mean, per 6-month cohort | +10.90% | +13.75% |
| **Net mean, per 6-month cohort** | **+10.85%** | **+13.70%** |
| Net median | +9.40% | +13.01% |
| Net win rate | 83.8% | 85.3% |
| Net worst-5%-mean (tail loss) | −11.26% | −18.41% |
| Net mean under adverse cost (15bps) | +10.75% | +13.60% |

**Both are strongly positive in absolute terms — this is the "rising
market alone" effect this task's own instruction explicitly warned
against over-crediting to the selection rule.** SPY's own total return
over the identical 2019-01-02→2026-08-31 window was **+242.68%** (fully
invested throughout) — a strong secular bull run. Both Strategy A and
Benchmark B1's positive absolute 6-month returns are consistent with
simply being long large-cap U.S. equities during this period, not
evidence the 52-week-high SELECTION mechanism specifically works.

## Benchmark-relative (incremental) economics — the primary estimand

**Strategy A minus Benchmark B1, paired by formation date, net of the
same 5bps cost on both sides**:

- **Mean incremental**: **−2.846%** per 6-month cohort — **the selected
  (top-30%-nearest-to-52-week-high) portfolio UNDERPERFORMED simply
  holding the whole eligible universe**, on average.
- **95% CI (non-overlapping 6-month block bootstrap, 12 blocks, 5,000
  reps, seed 127127)**: **[−6.96%, +0.23%]** — includes zero, barely
  (the upper bound sits just above zero).
- **9 of 12 non-overlapping 6-month blocks show a NEGATIVE incremental
  mean**; only 3 are positive. The negative-leaning pattern is
  consistent across most of the window, not driven by one outlier
  period.
- Strategy A's own ABSOLUTE 6-month return uncertainty (same block
  method): 95% CI **[+6.25%, +15.99%]** — entirely positive, clearing
  the materiality band easily on an absolute basis. **This positive
  absolute CI does NOT, by itself, justify the strategy** — Benchmark
  B1's absolute return is HIGHER (+13.70% vs. +10.85%), meaning the
  extra selection complexity actively subtracted value relative to the
  simple alternative, exactly the failure mode this task instructed
  against attributing to "the selection rule."

## Concentration

Strategy A's 68 realized cohorts drew from 37 of 38 possible issuers.
Selection counts range from MCD (37 selections) and PG (33) down to
INTC (4) and ACHR (2) — a reasonably broad spread, not dominated by a
single name; concentration is not the driver of the negative
incremental result.

## Uncertainty method and its acknowledgment of dependence

Both the incremental and Strategy A's own absolute-return uncertainty
use the SAME **non-overlapping 6-month block bootstrap** — collapsing
68 overlapping, correlated monthly cohorts (which share holding-period
market dates and heavily overlapping stock membership across adjacent
formation months) down to **12 genuinely non-overlapping 6-month
macro-blocks**, the honest count of dependent units in a ~7.5-year
window under a 6-month hold. **68 trades is explicitly NOT treated as
68 independent observations** — nor is this called "properly powered"
from that or any other count; 12 blocks is a small number of truly
independent periods, disclosed as a genuine limitation, not glossed
over.

## Limitations

- **Survivorship**: the 38-symbol universe is today's (2026-09-13)
  active configured watchlist projected backward — not a true
  historical point-in-time universe. A name that would have
  underperformed enough to be dropped from a hypothetical past
  watchlist is invisible here by construction. This inflates BOTH
  Strategy A's and Benchmark B1's absolute returns similarly (both use
  the identical universe), so it should not by itself explain the
  NEGATIVE incremental result, but it does mean neither absolute figure
  should be read as a historically achievable, unbiased return.
- **12 non-overlapping blocks** is a small sample for a 6-month-hold
  study — a structural limitation of testing any 6-month-hold
  hypothesis on ~7.5 years of data, not a defect in this task's method.
- **SPY comparison is not apples-to-apples** with the chronological
  strategy/benchmark portfolios due to differing capital utilization
  (SPY fully invested; strategy portfolio ≈74% average utilization) —
  reported for context only, not as the primary comparison.
- Corporate-action handling (splits) was directly verified continuous
  under `adjustment=all` (§4 of the frozen protocol); dividends are
  embedded consistently on both the strategy and both benchmark sides.
  No delisting-aware panel was used (disclosed, not worked around).

## Statistical verdict

> **`INCONCLUSIVE`**

The incremental 95% CI **[−6.96%, +0.23%]** includes zero (its upper
bound only barely crosses positive) — per the frozen criteria, this
does not meet the bar for `DOES_NOT_SUPPORT_PREDECLARED_EFFECT` (which
requires a CI entirely negative) nor `SUPPORTS_PREDECLARED_EFFECT`. The
point estimate is negative and 9 of 12 blocks agree in sign, but the
formal CI test does not cross zero cleanly enough to call this a
statistically confirmed negative effect either.

## Product verdict

> **`DO_NOT_ADVANCE`**

Applying the frozen product criteria: `ADVANCE_TO_FURTHER_VALIDATION`
requires `SUPPORTS_PREDECLARED_EFFECT` AND a positive, economically
credible absolute return — neither the statistical precondition holds
(verdict is `INCONCLUSIVE`, not `SUPPORTS`) nor would the incremental
comparison support advancing even if it were on the margin: the
frozen protocol's own explicit instruction is *"if negative or
inadequate, archive this exact contract"* — the incremental point
estimate IS negative (−2.846%), does not clear the ±10bps materiality
band in the positive direction, and the underlying absolute-return
picture is a clean demonstration of exactly what this task warned
against: *"positive absolute returns during a rising market alone do
not justify a more complex selection strategy."* Benchmark B1 (simply
holding the eligible universe, no selection at all) achieved a HIGHER
absolute return than the tercile-selected strategy. The added
complexity of 52-week-high tercile selection is not justified by this
evaluation.

## One next action / explicit stop decision

**Explicit stop.** Archive this exact contract (38-symbol universe,
tercile selection by 252-day-high proximity, monthly formation,
6-month overlapping holds) as tested — negative/inadequate incremental
result, per the frozen criteria. No parameter variation (a different
ranking fraction, lookback window, or holding period), no ticker
subset search, no shorter holding period, and no indefinite live-
observation programme are proposed, per this task's own explicit
instruction. Turn-of-month remains separately closed (Task 126,
un-re-evaluated). No candidate in this research program currently
carries an `ADVANCE_TO_FURTHER_VALIDATION` product verdict pending
action.
