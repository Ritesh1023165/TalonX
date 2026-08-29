# Task 81-R2 §6 — Corrections to earlier Task 81 / R1 evidence

Earlier reports are **preserved unchanged**. These are the authoritative
corrections.

## C1 — R1 skip-attribution was wrong

`results/task81_r1_recovery_closure/xfail_skip_disposition.md` (row S1) and
the R1 report stated the skipped assertion
`tests/test_backtest_cost_sensitivity.py::test_higher_cost_never_improves_expectancy`
skips because "`sample_AAPL_trade_1m.csv` yields exactly 1 trade".

**Incorrect.** That test's `scenario_rows` fixture is built from `sample_df`,
which is a small **generated, deliberately trade-FREE** fixture
(`_small_bars(140)` in `test_backtest_cost_sensitivity.py`) — NOT
`sample_AAPL_trade_1m.csv`. It produces **zero** trades, so
`len(expectancies) < 2` and the test skipped.

Correct disposition (this task): `test_higher_cost_never_improves_expectancy`
is rewritten to **assert the zero-trade behaviour explicitly** (all
scenario rows report 0 trades and `expectancy_r is None`) — it no longer
skips. The expectancy-versus-cost monotonicity assertion is exercised with
a trade-producing fixture by
`test_multi_trade_higher_cost_never_improves_expectancy_without_skipping`
(previously xfailed, now passing against the regenerated
`sample_multi_trade_1m.csv`). No replacement skip/xfail marker is
introduced.

## C2 — the ten xfails were NOT "not fixable in this line of work"

`results/task81_r1_recovery_closure/xfail_skip_disposition.md` classified
all ten `test_multi_trade_*` xfails as RETAINED, deferring the
`sample_multi_trade_1m.csv` regeneration as an out-of-scope "dedicated
follow-up".

Under Task 81-R2, synthetic-fixture regeneration was **explicitly
authorized**. All ten xfails and the one skip are now **closed** by
regenerating `examples/data/sample_multi_trade_1m.csv` deterministically
(generator: `scripts/gen_sample_multi_trade_1m.py`; specification:
`fixture_spec.md`) using the **unchanged** strategy. Each xfail marker was
removed only after its underlying test passed. See `xfail_skip_closure.md`.

The root-cause statement itself was accurate: the previous fixture's
TSTW/TSTL/TSTE "trades" were built on the long/short bug (BEARISH-while-flat
shorts) removed in Task 24/25A, and the file was also far too short for the
200-bar/15-minute HTF warmup.

## C3 — test-count phrasing in the R1 report

The R1 report's per-file case counts ("(9)" for
`test_task81_r1_missing_identity_recovery.py`) referred to test
*functions*; `pytest --collect-only` counts *items* (parametrization
expands some). The R1 final full-suite delta was reconciled correctly
(`2597 + 28 = 2625`, verified by `--collect-only`); only the per-file
parenthetical counts were function-counts, not item-counts. No numeric
conclusion changes.

## C4 — IEX conclusion remains bounded (unchanged from R1 §6, restated)

`results/task81_safety_baseline_closure/iex_findings.md` and
`results/task81_r1_recovery_closure/iex_evidence_correction.md` stand.
Restating the bound so it is not lost:

- The Task 80 readiness-event **counts reconcile exactly** and match the
  independently-written `freshness_report.json`. This proves the runtime
  **bookkeeping** is sound (no double-count / drop / mis-route).
- It does **not** establish *why* the bars were missing, and it does
  **not** exclude a **receipt-time vs source-time** freshness problem
  (a delivered-late bar whose market timestamp is already older than
  `stale_seconds` still resets the wall-clock staleness anchor).
- IEX print sparsity is the **plausible** explanation; it is **not
  verified** for that session. This is a **disclosed, evidence-limited
  follow-up** — it must not be presented as a proven absence of defects.

### Minimum future capture to close C4

A session run (or a captured raw `GET /v2/stocks/bars/latest` response
log) recording, per bar: `symbol`, source bar timestamp `t`, and the
receipt wall-clock time — for at least REGN, VRTX, COST, HON, GILD, ISRG
across a full regular session — cross-checked against Alpaca's historical
IEX 1-minute archive via the existing `talonx_piv/gap_forensics.py`. No
data acquisition or session launch was performed to manufacture closure.

## Impact

None of these corrections changes the recovery / reconciliation / accounting
safety verdict. C1–C3 are closed in this task; C4 remains an explicit
disclosed limitation and is **not** an isolation blocker (feed-cadence
questions are independent of Original/PIV separation).
