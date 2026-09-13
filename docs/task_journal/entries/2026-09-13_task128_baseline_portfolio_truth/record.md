# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` HEAD:
  `671a07b2bc81f8fd246348985c9904ca268b1876` (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), `git status --short` clean.
- No TalonX process running, no listening ports on 8787/8770/8760/
  8501. Redis reachable, 0 `talonx:*` keys.

## Actions taken, in order

1. Located the exact overclaiming phrases in
   `docs/research/TASK127_LONG_TERM_ECONOMIC_DECISION.md`,
   `PRODUCT_STATUS.md`, and `TALONX_RESEARCH_LEDGER.md` (grep-verified,
   not assumed) and appended a dated correction blockquote to the
   economic-decision document's top, addressing all four required
   corrections.
2. Read `research/scripts/task127_52wk_high_evaluation.py` directly and
   confirmed: `benchmark_B1_summary["net_mean_pct"]` =
   `100 * np.mean(net)` over 68 independent `cohort_gross_net_return`
   outputs — an arithmetic mean of cohort-level point returns, NOT a
   chronological portfolio return; and that `run_chronological_portfolio`
   (already generic/parameterized) was only ever invoked for Strategy
   A, never for Benchmark B1.
3. Wrote and committed `docs/research/TASK128_BASELINE_CONTRACT_AND_ACCOUNTING.md`
   Parts 1-3 (commit `dea4095`, pushed) — corrections summary, the
   exact restated Benchmark B1 contract, and the frozen assessment
   protocol — BEFORE any new calculation was run.
4. Wrote `research/scripts/task128_baseline_chronological_reconciliation.py`,
   reusing `task127_52wk_high_evaluation.py`'s existing `load_all`,
   `build_cohorts`, `Cohort`, `_price_on_or_none` UNCHANGED; added one
   new function (`run_chronological_portfolio_daily`) extending the
   existing monthly-marking chronological portfolio to daily marking
   (the smallest faithful extension, not a new engine), plus a
   same-capital/same-dates daily-marked SPY comparator.
5. Wrote `tests/test_task128_chronological_reconciliation.py` (4 tests:
   no negative cash/equity reconciliation, insufficient-cash guard
   behavior, drawdown/recovery-duration on a known synthetic path, SPY
   fully-invested-from-day-1 behavior) and ran them BEFORE the real
   evaluation — 1 initial failure from an incorrect test assumption
   (not a code defect, fixed), then all 4 passed.
6. First real run hung on the naive per-date price-lookup pattern (same
   O(n_dates × n_rows) bottleneck seen in earlier tasks this session)
   — stopped via `TaskStop`, rewrote the marking loop to use a
   precomputed, forward-filled, indexed close-price lookup per symbol
   (O(1) per date instead of a DataFrame re-filter) — re-ran the fixture
   tests (still 4/4 pass, now in 1.55s) and the real reconciliation
   completed in ~13s.
7. Ran the real reconciliation: Benchmark B1 chronological portfolio
   (base + 15bps adverse cost), Strategy A's own chronological daily
   portfolio (for the Part 5 fair comparison), and SPY (same $100k,
   same dates, daily-marked, fully invested from day 1). Confirmed the
   one insufficient-cash skip (2020-12-01 entry) is a real, disclosed
   instance of the no-leverage guard binding due to cumulative small
   entry costs across 6 filled slots — not a bug.
8. Wrote `docs/research/TASK128_BASELINE_CONTRACT_AND_ACCOUNTING.md`
   Parts 4-6 (reconciled results, fair comparison, survivorship-bias
   audit) and `docs/research/TASK128_BASELINE_PRODUCT_DECISION.md`
   (Parts 7-8: product specification, bounded decision
   `USEFUL_AS_TRACKING_BENCHMARK_ONLY`).
9. Copied compact evidence (`chronological_reconciliation.json` 5.8KB,
   `benchmark_b1_realized_trades.json` 48KB — the 351KB full daily
   equity curve kept local-only per this program's evidence-size
   convention) to `docs/research/evidence/task128/`.
10. Updated `docs/research/PRODUCT_STATUS.md` (new row, corrected the
    52-week-high row's overclaimed language, updated header date) and
    `docs/research/TALONX_RESEARCH_LEDGER.md` (Task 128 pointer entry)
    and `docs/task_journal/TASK_INDEX.md`.
11. Re-verified production/Redis/process preservation (same result as
    baseline).

## Key finding: what the original +13.70% actually was

Confirmed via direct code read (not inference): an unweighted
arithmetic mean of 68 individual 6-month cohort point returns. The
TRUE chronological $100k portfolio result (built for the first time
this task) is materially different in kind (though directionally
consistent): +151.13% total / +12.77% annualized, with a real, bounded,
recovered −19.58% drawdown.

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`.
