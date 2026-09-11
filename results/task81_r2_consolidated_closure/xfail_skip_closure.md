# Task 81-R2 §5 — xfail / skip closure table

All 10 `_XFAIL_PENDING_SAMPLE_DATA_REGENERATION` xfails and the 1
conditional skip are **CLOSED** by regenerating
`examples/data/sample_multi_trade_1m.csv` deterministically via the
UNCHANGED strategy (`scripts/gen_sample_multi_trade_1m.py`;
`fixture_spec.md`). No strategy rule was weakened, no coverage deleted, no
replacement skip/xfail marker introduced. Each marker was removed only
after its underlying test passed against the new fixture.

Root cause (accurate, from R1): the previous fixture's TSTW/TSTL/TSTE demo
trades were built on the long/short bug removed in Task 24/25A **and** the
file was ~2 trading days (< the ~8 the 200-bar/15-min HTF warmup needs),
so it produced 0 trades. R1 deferred the regeneration as out of scope;
R2 explicitly authorised it and it is done.

| # | Node id | Was | Now |
|---|---|---|---|
| 1 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_runs_the_documented_command_and_produces_three_trades` | xfail (0 trades) | PASS — `trades_executed == 3` |
| 2 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_exercises_target_stop_and_eod_exit_reasons` | xfail | PASS — `{TSTW:TARGET, TSTL:STOP, TSTE:END_OF_SESSION}` |
| 3 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_has_at_least_one_winner_and_one_loser` | xfail | PASS — TSTW/TSTE win, TSTL `gross_R == -1.0` |
| 4 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_populates_aggregate_statistics` | xfail | PASS — `winning=2 losing=1 avg_loss_r=-1.0 max_dd_r=-1.0 total_r>0 win_rate=2/3` |
| 5 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_equity_curve_reflects_the_win_loss_sequence` | xfail | PASS — `len(lines)==4`, `cum[0]<0`, `cum[-1]>0`, `cum[-1]==max` |
| 6 | `tests/test_backtest_sample_data.py::test_multi_trade_dataset_html_report_contains_populated_metrics` | xfail | PASS — HTML payload `total_trades==3 winning==2 losing==1`, exit reasons `{TARGET,STOP,END_OF_SESSION}` |
| 7 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_fixture_produces_three_trades_in_every_scenario` | xfail | PASS — `[3,3,3,3]` |
| 8 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_net_r_actually_changes_with_cost` | xfail | PASS — `total_r` strictly decreases 0→5→10→20 bps |
| 9 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_higher_cost_never_improves_expectancy_without_skipping` | xfail | PASS — expectancy strictly decreases; never skips |
| 10 | `tests/test_backtest_cost_sensitivity.py::test_multi_trade_trade_count_and_win_loss_mix_are_cost_invariant` | xfail | PASS — `{3}` trades and `win_rate==2/3` at every bps |
| S1 | `tests/test_backtest_cost_sensitivity.py::test_higher_cost_never_improves_expectancy` (conditional `pytest.skip`) | SKIPPED — `sample_df` (`_small_bars`, generated trade-free) yields < 2 expectancies | RENAMED `test_zero_trade_fixture_reports_no_expectancy_in_any_scenario`; asserts `{trades}=={0}` and `expectancy_r is None` for every scenario — **explicit zero-trade coverage, no skip**. The expectancy-vs-cost monotonicity assertion it used to attempt is exercised with a trade-producing fixture by row 9. Attribution corrected (`report_corrections.md` C1): the fixture is `_small_bars()`, not `sample_AAPL_trade_1m.csv`. |

## Preserved coverage

- `test_backtest_sample_data.py` zero-trade smoke fixture tests
  (`test_smoke_dataset_*`) and the single-trade fixture tests
  (`test_trade_dataset_*`) are unchanged.
- `test_backtest_cost_sensitivity.py::test_trade_count_is_identical_across_cost_scenarios`,
  `test_zero_cost_scenario_matches_a_plain_zero_cost_backtest`, and the
  `sample_df`-mechanics tests are unchanged; only the previously-skipping
  test was rewritten to a real zero-trade assertion.
- `test_multi_trade_dataset_signals_satisfy_the_frozen_strategy_naturally`
  (never xfailed; previously vacuous with 0 trades) now genuinely asserts
  `confluence_score >= 2` and `risk_reward_ratio >= 1.5` for all three
  trades.

## Verdict

10 xfails + 1 skip resolved with no strategy change, no coverage deletion,
no new skip/xfail markers.
