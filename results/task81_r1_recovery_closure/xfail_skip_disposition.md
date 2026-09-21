# Task 81-R1 §5 — Expected-failure inventory and disposition

Baseline re-run (`raw_test_output/baseline_full_suite.txt`, HEAD
`81d18d5`): **`2597 passed, 1 skipped, 10 xfailed`**, exit 0 — exact
match to the reported baseline.

`--runxfail` executed to expose the underlying failures
(`raw_test_output/xfail_runxfail.txt`; one representative run recorded
inline below).

## Summary

All **10 xfailed** cases and the **1 skipped** case share a **single root
cause**: `examples/data/sample_multi_trade_1m.csv` is a stale synthetic
demo dataset. Its TSTW/TSTL/TSTE "trades" were authored around the
long/short bug (a BEARISH `macd_bearish_cross` opening a SHORT while flat)
that Task 24/25A deliberately removed, and the file spans only 2 trading
days — far short of the ~7.7 days the unmodified 200-bar/15-minute HTF
trend gate (`talonx_quant/consumer.py`, `config.htf_sma_period=200`)
needs to yield a non-`None` `htf_sma_200`. Under the corrected,
long-only, unmodified strategy the file therefore produces **0 trades**.

- **Not a production defect.** The production strategy is correct; it is
  the demo fixture that is obsolete. `talonx_quant/*` is unchanged and
  out of scope.
- **Not a baseline-safety or dual-run concern.** Every affected test is a
  `talonx_backtest` demo-dataset *report-population* test
  (`python -m talonx_backtest --data sample_multi_trade_1m.csv ...`).
  None share any code path with reconciliation, recovery, session
  identity, the PIV live loop, or the planned Original/PIV dual run.
- **Fix = a dedicated synthetic-data regeneration follow-up**, explicitly
  scoped as such by the marker itself since Task 25A (2026-08-20) and
  tracked in `results/task25a_long_only_parity_fix/task25a_summary.md`.
  It requires authoring, for each of 3 independent symbols, ~9 trading
  days of quiet HTF-warmup preroll plus a MACD-bullish-cross + RSI-through-
  30 + volume-surge-2x + close-above-`htf_sma_200` + structural-R:R setup,
  empirically calibrated against the real indicator/aggregation/strategy
  code, landing the three trades on exactly `TARGET` / `STOP` (gross_R ≈
  −1.0) / `END_OF_SESSION` — the same class of work Task 73S did for the
  single-symbol fixture (which needed several iterations and a 3-bar
  extension just to land one `TARGET`). This is new synthetic-data
  authoring, not a bug fix; per Task 81-R1 §8 it is documented here rather
  than pulled into a recovery-integrity task.

**Disposition: RETAINED — all 10 xfails and the 1 skip.** The markers are
**accurate, not obsolete** (`--runxfail` confirms `trades_executed == 0`
today), so per §5 they must not be removed. `strict=True` keeps them
honest: a future CSV regeneration is forced to delete the marker (xpass →
error).

**Isolation-blocker assessment: NONE.** Retaining these changes nothing
about the readiness of the recovery/reconciliation baseline for
Original/PIV separation.

## Per-case table

| # | Node id | Marker | Underlying result (`--runxfail`) | Root cause | Baseline-safety / dual-run relevance | Fix | Disposition |
|---|---|---|---|---|---|---|---|
| 1 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_runs_the_documented_command_and_produces_three_trades` | `xfail(strict=True)` "Task 25A … CSV-regeneration follow-up" | `assert summary["trades_executed"] == 3` → `assert 0 == 3` | stale demo CSV (long/short-bug trades + <8d HTF warmup) → 0 trades | none — backtest demo report test | regenerate `sample_multi_trade_1m.csv` (3 long setups, ~9d preroll each) | RETAIN |
| 2 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_exercises_target_stop_and_eod_exit_reasons` | same | `backtest_trades.json` empty → `KeyError`/`StopIteration` on exit-reason map | same | none | same | RETAIN |
| 3 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_has_at_least_one_winner_and_one_loser` | same | no trades → `any(r>0)` / `any(r<0)` both False | same | none | same | RETAIN |
| 4 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_populates_aggregate_statistics` | same | `net["winning_trades"] == 2` → `0 == 2`; profit factor / avg-loss are None/degenerate | same | none | same | RETAIN |
| 5 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_equity_curve_reflects_the_win_loss_sequence` | same | `backtest_equity_curve.csv` header-only → `len(lines) == 4` → `1 == 4` | same | none | same | RETAIN |
| 6 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_html_report_contains_populated_metrics` | same | HTML payload `metrics.net.total_trades` == 0 → `0 == 3` | same | none | same | RETAIN |
| 7 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_fixture_produces_three_trades_in_every_scenario` | same | `[r["trades"] …] == [3,3,3,3]` → `[0,0,0,0]` | same (via `cost_sensitivity_scenarios`) | none | same | RETAIN |
| 8 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_net_r_actually_changes_with_cost` | same | `total_r` values are `None` (no trades) → `all(v is not None)` False | same | none | same | RETAIN |
| 9 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_higher_cost_never_improves_expectancy_without_skipping` | same | `expectancy_r` values `None` → `all(v is not None)` False | same | none | same | RETAIN |
| 10 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_trade_count_and_win_loss_mix_are_cost_invariant` | same | `{r["trades"]} == {3}` → `{0} == {3}` | same | none | same | RETAIN |
| S1 | `tests/test_backtest_cost_sensitivity.py::test_higher_cost_never_improves_expectancy` (skip at line 87–90) | `pytest.skip("fixture produced too few trades to compare expectancy across scenarios")` | conditionally SKIPPED — `sample_AAPL_trade_1m.csv` yields exactly 1 trade, so `len(expectancies) < 2` | correct conditional guard; the single-symbol fixture is genuinely 1-trade (Task 73S). It is **not masking a defect**. The real multi-scenario expectancy-monotonicity assertion exists as case #9 above (behind the same CSV-regen follow-up). | none | none needed for the skip itself; case #9 covers the assertion once the CSV is regenerated | RETAIN (correct behaviour) |

## Representative `--runxfail` evidence

```
$ .venv/Scripts/python.exe -m pytest -p no:cacheprovider --runxfail \
    "tests/test_backtest_sample_data.py::test_multi_trade_dataset_runs_the_documented_command_and_produces_three_trades" -q

>       assert summary["trades_executed"] == 3
E       assert 0 == 3
tests\test_backtest_sample_data.py:283: AssertionError
1 failed in 36.36s
```
