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
