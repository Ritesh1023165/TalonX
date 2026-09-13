1. **Product verdict and historical-evidence limitations**: Product =
   **`USEFUL_AS_TRACKING_BENCHMARK_ONLY`**. Historical evidence: the
   no-selection baseline's chronological portfolio is genuinely
   positive (+12.77% annualized) over the one exploratory window
   tested, consistent with (not proven attributable to) broad market
   exposure, and materially underperforms simple SPY buy-and-hold with
   the identical capital (+17.44% annualized) — a real ~4.7-point gap,
   not a rounding difference. No factor-regression beta attribution
   was performed; non-overlapping bootstrap blocks are not proven
   statistically independent; survivorship bias cannot be quantified
   (no point-in-time watchlist snapshot exists).

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged (research-only task). Research `671a07b` (confirmed
   exact) → **`<this commit>`**, pushed to
   `research/talonx-profitability-2026-09` only. Protocol-freeze
   checkpoint pushed separately as `dea4095`.

3. **Exact baseline contract and meaning of +13.70%**: Benchmark B1 =
   monthly formation, ALL eligible symbols (≥252-day history, price
   ≥$5) equal-weighted (no selection), 6-month overlapping
   Jegadeesh-Titman-style holds, up to 6 concurrent cohorts, unchanged
   from Task 127. The original +13.70% is confirmed (direct code
   read) to be an **arithmetic mean of 68 individual 6-month cohort
   returns** — NOT a chronological portfolio return; Task 127's
   `run_chronological_portfolio` was only ever run for Strategy A.

4. **Chronological equity, costs, drawdown, reconciliation**: real
   $100k portfolio (reused existing function, extended to daily
   marking): ending equity **$251,128.98**, total return **+151.13%**,
   annualized **+12.77%**, max drawdown **−19.58%** (2022-01-03 peak →
   2022-10-12 trough → 2023-06-15 recovery, 528 days), 79.3% average
   capital utilization, 67/68 round trips realized (1 correctly
   skipped by the no-implicit-leverage guard — a real, disclosed
   instance, not a bug). 15bps adverse cost moves ending equity to
   $249,936.45 (−0.47%) — not cost-sensitive at these levels. Cash
   never negative; cash+marked=equity verified at every date; 0 open
   positions at the end (natural wind-down, not forced liquidation).

5. **Fair benchmark comparison**: SPY, same $100k, same dates, both
   marked daily: **+242.68% total / +17.44% annualized**, max drawdown
   −33.79% (recovered in 173 days). One deployment-timing difference
   disclosed (SPY fully invested day 1; baseline ramps to 79.3%
   average utilization) — not fully separated from selection effects,
   named as a residual limitation.

6. **Historical-membership and coverage limitations**: no verified
   point-in-time watchlist snapshot exists anywhere in the repo — the
   entire 38-symbol universe is today's watchlist projected backward.
   No delistings possible in this panel by construction (survivorship
   gap itself). 5 of 43 active configured tickers excluded for data-
   availability reasons (BABA/BLSH/SHOP/SKHY/SPCX), identical to
   Strategy A. No name removed after seeing its contribution.

7. **Concrete alert journey and usefulness**: described AS the actual
   tested contract (monthly batch entry/exit, no interim review, pure
   calendar-driven, no directional conviction) — NOT simplified into a
   buy-and-hold or single-rebalanced portfolio. Assessed as helping
   only partially (no ticker differentiation) and not materially more
   useful than a simple tracker given the SPY underperformance gap;
   drawdown/recovery are now precisely visible; kept conceptually
   separate from the still-unresolved intraday goal.

8. **One next action / stop decision**: reuse this task's corrected,
   daily-marked, cash-reconciled chronological implementation as the
   standard no-selection benchmark for any future long-term-horizon
   candidate evaluation — not productized as a standalone alert. No
   new parameter search, literature shortlist, or indefinite live
   observation proposed.

9. **Production preservation**: no release-branch change; no
   application process started; Redis `talonx:*` key count 0 both
   before and after; no stray/duplicate processes (the initial slow
   background run was stopped and replaced with an optimized
   foreground run before any output was trusted).

10. **Journal/reports**: `entries/2026-09-13_task128_baseline_portfolio_truth/`
    + `docs/research/{TASK128_BASELINE_CONTRACT_AND_ACCOUNTING,TASK128_BASELINE_PRODUCT_DECISION}.md`
    + `docs/research/evidence/task128/*.json` +
    `research/scripts/task128_baseline_chronological_reconciliation.py`
    + `tests/test_task128_chronological_reconciliation.py` — protocol
    freeze at `dea4095`, remainder at this commit, both pushed.

Priority followed as instructed: establish portfolio truth → assess
user value → make one decision, completed in this single task. The
baseline is now honestly reconciled — genuinely positive but not
differentiated, and clearly outperformed by the simplest available
alternative — reported as a benchmark-only usefulness finding, not a
product launch candidate.
