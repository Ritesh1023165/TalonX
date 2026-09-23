# Prospective V2 session -- final report
generated: 2026-09-23T20:13:52.509640+00:00 (2026-09-23T21:13:52.509640+01:00 Europe/London)
session dir: C:\workspace\TalonX\results\prospective_2026-09-23

## Verdict: PASS_WITH_FINDINGS

## Runtime health
- V2 service health: HEALTHY (tick 322, heartbeat 0.0s)
- market feed: HEALTHY (coverage 1.0)
- Intelligence processing log age: 137.020636s; newest insider event 2026-09-23T16:01:03+00:00
- release: HEAD 9f0ab38 (v1 fp ok=True, v2 fp ok=True)

## V2 near-miss funnel
- Form 4 code-P records (window / today): 11 / 1
- distinct issuers with code-P (window / today): 3 / 1
- single-insider near-miss issuers: 1 ['INTC']
- >=2-distinct-insider clusters: 2 ['ABCL', 'ADC']
- stale historical clusters (skipped): 1
- fresh eligible clusters: 1
- V2 signals / BUY / SELL: 0 / 0 / 0
- interpretation: REVIEW_POSSIBLE_SUPPRESSION

## Paper account (V2 campaign ledger)
- starting cash: 100000.0
- current cash: 100000.0
- open positions: 0 / 20   (open cost 0.0)
- closed positions: 0   realized P&L 0.0
- EXIT_UNRESOLVED: 0

## EOD asserts
- buys_eq_sells_plus_open_plus_unresolved: PASS
- cash_plus_open_cost_reconciles: PASS
- no_negative_cash: PASS
- whole_share_positions: PASS
- positive_finite_position_cost: PASS
- corporate_action_adjustments_consistent: PASS
- dividend_accounting_consistent: PASS
- no_duplicate_buy_episode_id: PASS
- no_duplicate_position_episode_id: PASS
- no_stale_episode_entered: PASS
- no_illegal_eod_flatten: PASS
- real_capital_off: PASS
- shorts_off: PASS
- experimental_external_sends_zero: PASS
- no_cross_lane_contamination: PASS
- official_dispatch_healthy: PASS
- base_reconciliation: PARTIAL
- v2_ledger_preserved_copy: PASS
- lane_accounting_snapshot: PASS
- controlled_shutdown_complete: PASS

## Findings
- base eod_reconciliation PARTIAL (typically: no PIV reader) -- mismatches=[]

## Shutdown
- {"checkpoint_daemon": {"status": "stopped", "signalled": 3632, "tree_size": 3, "reaped": [], "residual": []}, "v2_companion": {"status": "stopped", "signalled": 14592, "tree_size": 3, "reaped": [], "residual": []}, "supervisor": {"status": "stopped", "signalled": 8932, "tree_size": 11, "reaped": [], "residual": []}, "residual_talonx_processes": [], "overall_budget_s": 120.0, "elapsed_s": 3.5, "ports": {"8787": false, "8760": false, "8770": false, "8501": false}, "pid_registry_cleared": true, "v2_lane_db_intact": true, "startlock_released": true, "performed": true, "open_v2_positions_preserved": true, "shutdown_clean": true}

## Campaign
- day 12 (started 2026-09-08); prospective sample still SAMPLE_INSUFFICIENT until real prospective trades accumulate
- ledger preserved; carries forward. No profitability inference from zero-trade days.