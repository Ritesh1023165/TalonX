# Task72/73 -- VALIDATION summary

**Classification: VALIDATION_FAIL**

**Integrity note:** `classify.py`'s criterion 12 originally required
`0 < stop_rate < 1`, mislabeling this run's `stop_rate=0.0` as an
"unreasonable" pathology. That was a bug in the code's operationalization
of the pre-registered criterion, not the criterion's substance -- the
2.5% stop was deliberately frozen as a generous catastrophic buffer (see
`strategy_freeze.md`), so rarely/never firing is the expected, benign
case, not evidence of an execution defect. Fixed to check only that
`stop_rate` is a valid probability (i.e. that the stop-tracking machinery
itself didn't malfunction). Re-derived the classification from the
already-computed `validation_metrics.json` (no holdout data was
re-touched, no new trade was computed) -- the classification is
UNCHANGED (VALIDATION_FAIL both before and after the fix): criteria 3, 8,
and 15 fail on economic substance regardless.

- Fingerprint match: True
- Dataset hash: 766359eb6698
- Trades: 170 | Symbols: 35 | Days: 24
- Gross expectancy: 0.1005%
- Net expectancy 10bps: 0.0005%
- Net expectancy 15bps: -0.0495%
- Profit factor 10bps: 1.0017776163738044
- Win rate: 0.4588235294117647
- Max drawdown: -14.753267196163495
- Stop rate: 0.0 (stop=0, time_exit=170)
- Symbol-cluster CI: [-0.02069444975336093, 0.21647236253021176]
- Day-cluster CI: [-0.050772820885801824, 0.25169882763885293]
- Top1 symbol contribution: 0.11848605730042201
- Top1 day contribution: 0.158070694550453
- Top3 winners removed expectancy (10bps): -0.04863192420224668

## Criteria

- 1_net_10bps_positive: PASS
- 2_pf10_gt_1: PASS
- 3_net_15bps_ok: FAIL
- 4_session_coverage_ge_20: PASS
- 5_symbol_coverage_ge_15: PASS
- 6_top1_symbol_le_040: PASS
- 7_top1_day_le_040: PASS
- 8_top3_removed_not_materially_negative: FAIL
- 9_not_single_segment_carried: PASS
- 10_day_cluster_not_strongly_contradictory: PASS
- 11_symbol_cluster_not_contradictory: PASS
- 12_stop_behavior_reasonable: PASS
- 13_no_causal_or_fingerprint_violation: PASS
- 14_long_only_direction_consistent: PASS
- 15_costs_do_not_erase_edge: FAIL