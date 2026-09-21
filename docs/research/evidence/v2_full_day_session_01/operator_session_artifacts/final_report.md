# Prospective V2 session -- final report
generated: 2026-09-21T20:06:22.385378+00:00 (2026-09-21T21:06:22.385378+01:00 Europe/London)
session dir: C:\workspace\TalonX\results\prospective_2026-09-21

## Verdict: PASS_WITH_FINDINGS

## Runtime health
- V2 service health: HEALTHY (tick 34, heartbeat 1.0s)
- market feed: HEALTHY (coverage 1.0)
- Intelligence processing log age: 56.995615s; newest insider event 2026-09-21T08:59:54+00:00
- release: HEAD 0130a13 (v1 fp ok=True, v2 fp ok=True)

## V2 near-miss funnel
- Form 4 code-P records (window / today): 10 / 0
- distinct issuers with code-P (window / today): 3 / 0
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
- {"checkpoint_daemon": {"status": "stopped", "signalled": 14688, "tree_size": 3, "reaped": [], "residual": []}, "v2_companion": {"status": "stopped", "signalled": 8576, "tree_size": 3, "reaped": [], "residual": []}, "supervisor": {"status": "stopped", "signalled": 25460, "tree_size": 11, "reaped": [], "residual": []}, "residual_talonx_processes": [], "overall_budget_s": 120.0, "elapsed_s": 3.5, "ports": {"8787": false, "8760": false, "8770": false, "8501": false}, "pid_registry_cleared": true, "v2_lane_db_intact": true, "startlock_released": true, "performed": true, "open_v2_positions_preserved": true, "shutdown_clean": true}

## Campaign
- day 10 (started 2026-09-08); prospective sample still SAMPLE_INSUFFICIENT until real prospective trades accumulate
- ledger preserved; carries forward. No profitability inference from zero-trade days.