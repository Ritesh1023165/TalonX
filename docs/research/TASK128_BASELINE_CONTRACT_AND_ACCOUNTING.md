# Task 128 — baseline contract, accounting, and assessment protocol

Written and committed BEFORE `research/scripts/task128_baseline_chronological_reconciliation.py`
is run. Only reading Task 127's existing code/protocol/stored JSON
results (no new computation) preceded this freeze.

## Part 1 — corrections to Task 127 (see full text)

Applied directly to `docs/research/TASK127_LONG_TERM_ECONOMIC_DECISION.md`
as a dated blockquote (not reproduced in full here): "adds no value" →
"did not demonstrate added value in this evaluation"; non-overlapping
blocks are NOT proven statistically independent; "attributable to
broad market beta" softened to "consistent with" (no factor regression
was run); SPY's full-period total return and the 6-month cohort
average are flagged as different metric types, not directly comparable
without the chronological reconciliation this task performs. The
52-week-high tercile contract's `DO_NOT_ADVANCE` verdict is unchanged.

## Part 2 — the actual existing baseline contract (Benchmark B1)

Read directly from `research/scripts/task127_52wk_high_evaluation.py`
and `docs/research/TASK127_FROZEN_LONG_TERM_PROTOCOL.md` — restated
here precisely, not re-derived:

- **Eligibility / historical ticker population**: the SAME 38 active-
  covered configured tickers as Strategy A (union of
  `task95g_broad_cross_sectional/_daily` D1-precedence and
  `task107a_form4_feasibility/_prices` D2-fallback). At each monthly
  formation date, a symbol is eligible if it has ≥252 trading days of
  its OWN history as of that date AND `close ≥ $5.00`. Minimum 15
  eligible symbols required to form a cohort that month (18 of 92
  formation months were skipped for this reason — the ~13-month
  warm-up at the start of the window).
- **Formation schedule**: monthly, at the last trading day of each
  calendar month (identical to Strategy A).
- **Weighting**: EQUAL-WEIGHTED across **ALL** eligible symbols that
  month (no ranking, no selection at all — this is the "no-selection"
  control, NOT a subset).
- **Six-month holding/exit**: entry at the open of the first trading
  day of the FOLLOWING month; exit at the open of the first trading
  day 6 calendar months after entry. Identical mechanics to Strategy A.
- **Overlapping cohorts**: up to 6 concurrently open (one formed every
  month, each held 6 months) — the SAME Jegadeesh-Titman-style
  overlapping-portfolio design as Strategy A, NOT a single
  monthly-rebalanced portfolio and NOT a buy-and-hold. This is
  preserved exactly in this task; it is not converted to either
  alternative contract.
- **Starting capital / allocation** (as originally coded): $100,000
  total, 1/6 per concurrent cohort slot, equal-weighted within a
  cohort across that month's eligible names.
- **Costs**: 5bps round-trip base, 15bps adverse sensitivity, applied
  once per round trip (half at entry, half at exit, in the
  chronological accounting).
- **Dividend treatment**: `adjustment=all` (Alpaca SIP total-return
  back-adjustment) — embedded in the price series itself, identically
  for every symbol; not separately added.
- **Missing-data rule**: a symbol lacking its exact required
  entry/exit bar is excluded from that cohort and counted; never
  forward-filled for a MISSING TRADE bar (a distinct, narrower rule
  than the MARKING fallback below).

### What the originally reported +13.70% actually is

`benchmark_B1_summary["net_mean_pct"]` = `100 * np.mean(net)`, where
`net` is the list of 68 REALIZED cohorts' individual
`cohort_gross_net_return` outputs — **an unweighted arithmetic mean of
68 independent point-return observations, one per formation month**.
It is **not** a chronological portfolio return: it does not account
for capital reuse across overlapping cohorts, compounding, or the
timing of when capital was actually deployed versus idle. Task 127's
own `run_chronological_portfolio` function — already generic, already
parameterized by an arbitrary cohort list — was called only for
Strategy A; Benchmark B1's own chronological portfolio was never
built. **This task builds it, reusing that same function's contract
unchanged, extended only to mark every trading day instead of only
month-ends** (a strictly additive extension, not a new engine, per
this task's own "smallest faithful chronological implementation"
instruction).

## Part 3 — assessment protocol (frozen before new calculations)

- **Exact existing baseline contract**: Benchmark B1 exactly as
  restated in Part 2 above — unchanged, not re-optimized, not
  converted to a buy-and-hold or a monthly-rebalanced single portfolio.
- **Evaluation dates and pre-roll**: identical to Task 127 — data
  window 2019-01-02→2026-08-31 (union of the two daily directories);
  first ~13 months serve as unavoidable pre-roll (252-trading-day
  history requirement) before any cohort can form.
- **Research starting capital**: **$100,000**, entirely separate from
  and never connected to the production V2 $300k paper campaign or any
  live ledger — a fresh, isolated accounting instance for this
  assessment only.
- **Capital allocation across overlapping cohorts**: 1/6 of the
  $100,000 per concurrently-open cohort SLOT (unchanged from Task 127)
  — never more than 6 slots, never reusing capital already committed
  to an still-open cohort, never negative cash (an entry that would
  require more than currently-available cash is SKIPPED and recorded,
  not funded via implicit leverage).
- **Cash awaiting investment**: held as literal idle cash (0% yield
  assumed — no risk-free rate credited), explicitly visible in the
  equity reconciliation (`cash` + `marked_positions` = `equity`).
- **Costs**: SAME 5bps round-trip base + the SAME 15bps adverse
  sensitivity already predeclared in Task 127 — not a new number
  invented for this task.
- **Fractional shares**: permitted (this is a paper/research
  simulation; whole-share rounding is not modeled — disclosed, not a
  material distortion at this notional scale).
- **Dividend accounting / corporate actions**: unchanged from Task
  127 — `adjustment=all` embeds dividends once, consistently; no
  second addition anywhere in this task's own code.
- **Missing prices and unresolved positions**: a symbol missing a
  MARKING-date close (not a trade-execution date) uses its own last
  available close strictly ON OR BEFORE that date (never a future
  price) — the SAME causal fallback Task 127's own marking already
  used, now applied on every trading day instead of only month-ends;
  symbols marked this way are counted (`n_unresolved_stale_marks`) at
  every affected date, not silently absorbed.
- **Same-period comparator**: SPY, marked DAILY, the SAME $100,000
  starting capital, the SAME date range — but fully invested from day
  1 (the standard buy-and-hold convention), a DIFFERENT capital-
  deployment timing than the baseline's ramp-up, disclosed explicitly,
  not treated as a like-for-like allocation comparison.
- **Output metrics**: starting/ending equity, realized and unrealized
  P&L, gross vs. cost-adjusted, total return AND annualized return
  over the ACTUAL elapsed period, DAILY marked-equity drawdown with
  peak/trough/recovery dates and recovery duration in days, capital
  utilization (% of days with any open position), turnover (realized
  round-trip count), contribution by issuer (net P&L), open positions
  and unresolved valuations at the end of the window.
- **Decision criteria**: this task does NOT re-run or re-decide the
  52-week-high tercile contract (already closed `DO_NOT_ADVANCE`,
  Task 127, corrections applied Part 1 above). The decision made here
  (Part 8, `TASK128_BASELINE_PRODUCT_DECISION.md`) is a PRODUCT
  usefulness judgment on Benchmark B1 alone — `BASELINE_READY_FOR_FORWARD_PAPER_VALIDATION`
  / `USEFUL_AS_TRACKING_BENCHMARK_ONLY` / `DO_NOT_ADVANCE` /
  `BLOCKED_BY_SPECIFIC_ACCOUNTING_OR_DATA_LIMITATION` — kept explicitly
  separate from the historical economic evidence (positive absolute
  return, consistent with broad market exposure, not evidence of a
  differentiated edge).

No weighting, rebalance frequency, holding period, or ticker
composition is optimized anywhere in this task. The purpose is solely
to establish what Benchmark B1 actually delivers as a chronological
portfolio and whether that is a useful long-term paper-alert product —
not to improve its backtest.

## Part 4 — reconciled chronological portfolio (real results)

Run via `research/scripts/task128_baseline_chronological_reconciliation.py`
after 4 passing fixture tests (`tests/test_task128_chronological_reconciliation.py`
— no negative cash/implicit leverage, cash+marked=equity reconciliation,
insufficient-cash guard behavior, drawdown/recovery-duration on a known
synthetic path). Full output:
`results/task128_baseline_reconciliation/chronological_reconciliation.json`
(compact form copied to `docs/research/evidence/task128/`; the full
daily equity curve, 351KB, stays local-only per this program's
evidence-size convention).

| | Benchmark B1 (no selection) | Strategy A (tercile) | SPY (same $100k, same dates) |
|---|---:|---:|---:|
| Starting capital | $100,000 | $100,000 | $100,000 |
| Ending equity | **$251,128.98** | $218,662.44 | $342,677.81 |
| Total return | **+151.13%** | +118.66% | +242.68% |
| **Annualized return** (7.66 yrs elapsed) | **+12.77%** | +10.75% | +17.44% |
| Max drawdown (daily marked equity) | **−19.58%** | −14.54% | −33.79% |
| Drawdown peak → trough → recovery | 2022-01-03 → 2022-10-12 → 2023-06-15 | 2021-12-27 → 2022-09-30 → 2023-07-12 | 2020-02-19 → 2020-03-23 → 2020-08-10 |
| Recovery duration | 528 days | 562 days | 173 days |
| Recovery status | RECOVERED | RECOVERED | RECOVERED |
| Capital utilization (% days with ≥1 open position) | 79.3% | 79.3% | 100% (fully invested day 1) |
| Realized round trips | 67 | 67 | n/a (buy-and-hold) |
| Insufficient-cash skips | 1 (2020-12-01 entry) | 1 | n/a |
| Under 15bps adverse cost | ending equity $249,936.45 (+149.94%, +12.70% ann.) | — | n/a |

- **This is the first genuinely chronological, portfolio-level result
  for Benchmark B1** — Task 127 never computed one (§ Part 2 above).
  It confirms Task 127's ORIGINAL directional finding (Strategy A
  underperforms Benchmark B1) in a materially more rigorous form: a
  real $100k portfolio with capital constraints, realistic cost timing,
  and a genuine compounding path — not an unweighted average of 68
  independent point returns.
- **The one insufficient-cash skip (2020-12-01) is a real, disclosed
  instance of the "no implicit leverage" rule actually binding** — not
  a bug. With exactly 6 slots at `starting_capital/6` each, cumulative
  small entry costs (2.5bps per slot) leave slightly less than
  `6 × slot_capital` in cash once all 6 slots are ever filled
  simultaneously; on this one occasion the arithmetic came up ~$12
  short and the entry was correctly SKIPPED rather than funded via
  leverage. Effect: 67 of 68 possible entries realized, one entry
  forgone — economically negligible, structurally reassuring (the
  guard works).
- **Realized vs. unrealized P&L**: by the end of the tracked window
  (2026-08-31) both Benchmark B1 and Strategy A have **0 open
  positions** — the portfolio naturally winds down because no further
  cohort can be FORMED within the final ~6 months of available data
  (not a forced liquidation; no position was closed early solely to
  make the report flat — every closure above is a normal, scheduled
  6-month exit at its own predetermined date).
- **Contribution by issuer** (net $ P&L across all 67 realized round
  trips, Benchmark B1): top contributors MSTR (+$16,533), VRT
  (+$12,220), STX (+$11,374); only 3 of 38 issuers show a net loss
  (ACHR −$1,751, ABCL −$2,021, PYPL −$2,446) — broad-based, not
  concentrated in one or two names.
- **Gross vs. cost-adjusted**: the 15bps adverse-cost sensitivity
  moves ending equity from $251,128.98 to $249,936.45 — a ~$1,193
  (0.47%) difference over the full 7.66-year run. Costs are a minor
  factor relative to either the market-exposure return or the
  selection-vs-no-selection gap; this baseline's economics are NOT
  cost-sensitive at these cost levels.

## Part 5 — fair comparison (same capital, same dates, both marked daily)

SPY and Benchmark B1 use the **identical** $100,000 starting capital
and the **identical** 2019-01-02→2026-08-31 date range, both marked
DAILY (not the mismatched "full-period total return vs. per-6-month-
cohort average" comparison Task 127 originally made — corrected Part 1
above). **One deployment-timing difference remains and is disclosed,
not hidden**: SPY is conventionally fully invested from day 1, while
Benchmark B1 ramps up over its first ~13 months (252-day eligibility
warm-up) and averages 79.3% utilization thereafter (never negative
cash, per Part 4's own guard). This means part of the gap between
Benchmark B1's +12.77% and SPY's +17.44% annualized return reflects
**allocation/deployment timing**, not solely stock selection — the two
effects are NOT separated by this comparison alone (doing so would
require a fully-invested-from-day-1 variant of Benchmark B1's own
universe, which was not built — disclosed as a residual limitation,
not resolved by inventing a new contract in this task).

**No alpha is claimed from Benchmark B1's positive absolute return.**
Both Benchmark B1 and SPY were strongly positive over this specific
secular bull-market window; underperforming SPY by ~4.7 points of
annualized return is a real, material gap, not a rounding difference.
Whether the ADDED COMPLEXITY of running 38 individual, overlapping,
6-month-cohort positions is worth it FOR A USER, relative to just
holding SPY (or nothing, or a simpler tracker), is assessed on its own
terms in `TASK128_BASELINE_PRODUCT_DECISION.md` Part 7 — not inferred
from the return gap alone.

## Part 6 — retrospective watchlist-bias audit

- **Verified historical membership**: **NONE available.** No dated,
  point-in-time watchlist snapshot exists anywhere in this repository
  for any date before today (2026-09-13). This is stated directly, not
  worked around.
- **Today's watchlist projected backward**: **ALL 38** symbols used in
  this evaluation — the entire study population is today's active
  configured tickers, applied to historical prices. This is the SAME
  limitation already disclosed in Task 127 (Part 3, "Universe, snapshot,
  and historical-membership limitation") — restated here per this
  task's own explicit audit requirement, not newly discovered.
- **Pre-listing exclusions**: ABCL (first bar 2020-12-11) and ACHR
  (2020-12-18) are naturally excluded from every cohort's eligible pool
  until each individually accumulates 252 trading days of its OWN
  history (≈ late 2021/early 2022) — handled mechanically by the
  existing eligibility filter, not by any special-case code.
- **Missing or delisted names**: **NONE in this panel, by
  construction** — today's active watchlist cannot contain a name that
  was delisted, since a delisted name would not still be "active"
  today. This is the survivorship gap itself, not a separate mechanism
  needing separate handling.
- **Data-availability-driven exclusions**: **5 of the 43 currently-
  active configured tickers** (BABA, BLSH, SHOP, SKHY, SPCX) have no
  located daily-bar coverage in either of the two directories used and
  are excluded from BOTH Strategy A and Benchmark B1 identically — a
  coverage gap, not a performance-based exclusion (already established
  in Task 123/124/125/127).
- **Contribution table cross-check**: Part 4's issuer-contribution
  table shows 35 of 38 issuers net-positive and only 3 net-negative
  (ACHR, ABCL, PYPL) — no name was removed after seeing this outcome;
  all 38 remain in the reported universe regardless of their individual
  contribution sign, per this task's own explicit "do not remove
  successful or unsuccessful names after seeing outcomes" instruction.
- **Can survivorship bias be quantified here? No.** There is no
  point-in-time comparison universe available to measure the bias
  against — stated directly, not approximated with an invented
  substitute. Qualitatively: survivorship bias plausibly inflates BOTH
  Benchmark B1's and Strategy A's absolute returns similarly (both use
  the IDENTICAL 38-name universe), so it should not by itself explain
  the negative Strategy-A-vs-Benchmark-B1 gap (a within-universe
  comparison), but it does mean NEITHER absolute return figure — nor
  the SPY-relative gap — should be read as a historically achievable,
  unbiased return for a strategy that would have used a true
  historical point-in-time universe. No broader historical-membership
  reconstruction project is undertaken in this task.
