# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` HEAD:
  `7c8bcabc362f06dd5d339773475bd6ccd6a7c976` (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), `git status --short` clean.
- No TalonX process running, no listening ports on 8787/8770/8760/
  8501. Redis reachable, 0 `talonx:*` keys.

## Actions taken, in order

1. `WebSearch`/`WebFetch` used to verify George & Hwang (2004)'s actual
   methodology from the publisher record (Wiley/JF) and corroborating
   secondary sources explicitly describing the primary paper's design
   — confirmed TERCILE (30%) sort (correcting Task 122/126's "decile"
   description), monthly formation, Jegadeesh-Titman-style overlapping
   6-month holds, equal-weighted, $5 price filter, NYSE/AMEX/NASDAQ
   universe, ~2.99%/6mo long-short spread headline.
2. Read `results/task95b_swing_foundation/momentum_analysis.md`
   (release worktree) directly — found the closest prior TalonX test
   ("within 2% of the prior 20-day high," 3-5 day forward horizon,
   net excess −26.6 to −36.6bps) and confirmed it is a genuinely
   different anchor-window (20-day vs 252-day) and horizon (3-5 day vs
   6-month) combination, not an economically equivalent already-tested
   contract.
3. Wrote `docs/research/TASK127_PRODUCT_CONTRACT_CORRECTIONS.md` (Part
   1) — corrections to Task 126 appended, product contract updated.
4. Verified data availability (probes only, no returns): 38 active-
   covered configured tickers (union of `task95g_broad_cross_sectional/_daily`
   D1-precedence and `task107a_form4_feasibility/_prices` D2-fallback
   — same set Task 123 already used), per-symbol date ranges (33 from
   2019-06-03, 3 from 2019-01-02, 2 later-listed: ABCL 2020-12-11,
   ACHR 2020-12-18); confirmed SPY available in D2
   (2019-01-02→2026-08-31); directly verified `adjustment=all` shows a
   CONTINUOUS price series through both confirmed 2024 splits (AVGO
   2024-07-15, NVDA 2024-06-10) — no discontinuity, corporate-action
   handling verified rather than asserted.
5. Wrote and committed `docs/research/TASK127_FROZEN_LONG_TERM_PROTOCOL.md`
   (commit `241887e`, pushed) — BEFORE any return was computed. Freezes
   the full contract: tercile selection, monthly formation, 6-month
   overlapping holds, $100k chronological budget, 1/6 per concurrent
   slot, 5bps cost + 15bps adverse sensitivity, non-overlapping
   6-month block bootstrap (seed 127127), ±10bps materiality, two
   benchmarks, separate statistical/product acceptance criteria.
6. Wrote `research/scripts/task127_52wk_high_evaluation.py` implementing
   the frozen contract: causal rolling-252-day-high/nearness
   (vectorized via `pandas.rolling`), monthly cohort construction
   (tercile selection AND the no-selection Benchmark 1, via the same
   shared function), chronological capital-accounting portfolio
   simulator (cash/marked-positions/equity, monthly marking, drawdown
   from the marked equity curve), non-overlapping block bootstrap, SPY
   benchmark.
7. Wrote `tests/test_task127_52wk_high_fixture.py` (10 deterministic
   fixture tests covering causal rolling-high, tercile ranking, price/
   population eligibility filters, entry/exit timing, overlapping
   cohorts, capital allocation, cost application, missing-data
   exclusion, and cash/equity reconciliation) and ran them BEFORE the
   real evaluation. Two tests initially failed due to incorrect test
   assumptions (not code defects) — fixed and re-ran: **10/10 pass**.
8. Ran the frozen evaluation once (`task127_52wk_high_evaluation.py`,
   ~13s) against the real 38-symbol daily panel. Results: 92 formation
   months, 68 realized cohorts (18 skipped for insufficient eligible
   population during warm-up, 6 pending incomplete forward window).
   Strategy A (tercile) net +10.85%/6mo; Benchmark B1 (no selection)
   net +13.70%/6mo — HIGHER than the strategy. Incremental
   −2.846%/6mo, 95% CI [−6.96%,+0.23%] (non-overlapping 6-month block
   bootstrap, 12 blocks) — includes zero, negative in 9/12 blocks. SPY
   total return over the same window: +242.68% (fully invested,
   flagged as not apples-to-apples vs. the ~74%-average-utilization
   chronological portfolios).
9. Wrote `docs/research/TASK127_LONG_TERM_ECONOMIC_DECISION.md`
   applying the frozen decision criteria: statistical `INCONCLUSIVE`,
   product `DO_NOT_ADVANCE`.
10. Copied evidence (`task127_evaluation_results.json` 43KB,
    `portfolio_a_realized_trades.json` 25KB — both under the
    evidence-size convention) to `docs/research/evidence/task127/`.
11. Updated `docs/research/PRODUCT_STATUS.md` (new row, corrected
    "What this page is not" and header sections) and
    `docs/research/TALONX_RESEARCH_LEDGER.md` (Task 127 pointer entry)
    and `docs/task_journal/TASK_INDEX.md`.
12. Re-verified production/Redis/process preservation (same result as
    baseline).

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`.
