| scenario | endpoint | field | expected | actual | match |
|---|---|---|---|---|---|
| friday_reconciled | paper_eod | experimental_validation_paper.performance.realized_pnl.campaign_to_date | -324.4662160270568 | -324.4662160270568 | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.trade_counts.entries_today | 0 | 0 | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.trade_counts.exits_today | 4 | 4 | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.trade_counts.entries_campaign_to_date | 5 | 5 | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.open_positions.detail[0].unrealized_pnl_usd | 50.3019 | 50.3019 | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.open_positions.detail[0].mark_session_classification | POST_CLOSE | POST_CLOSE | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.reconciliation.status | EXACT | EXACT | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.costs.modeled | True | True | YES |
| friday_reconciled | paper_eod | experimental_validation_paper.performance.costs.explicit_commissions_fees | NOT modelled -- deliberate (assumes a commission-free retail broker, per talonx_paper/config.py's own docstring) | NOT modelled -- deliberate (assumes a commission-free retail broker, per talonx_paper/config.py's own docstring) | YES |
| friday_reconciled | v2_active_strategy | ledger.performance.cash | 300000.0 | 300000.0 | YES |
| friday_reconciled | v2_active_strategy | ledger.performance.reconciliation.status | EXACT | EXACT | YES |
| friday_reconciled | v2_active_strategy | ledger.performance.costs.modeled | False | False | YES |
| no_trades | paper_eod | original_local_paper.performance.open_positions.count | 0 | 0 | YES |
| no_trades | paper_eod | experimental_validation_paper.performance.open_positions.count | 0 | 0 | YES |
| no_trades | paper_eod | experimental_validation_paper.performance.unrealized_pnl.status | N/A -- zero open positions (a valid 0) | N/A -- zero open positions (a valid 0) | YES |
| open_position_missing_price | paper_eod | experimental_validation_paper.performance.open_positions.detail[0].mark | None | None | YES |
| open_position_missing_price | paper_eod | experimental_validation_paper.performance.equity.status | PARTIAL | PARTIAL | YES |
| open_position_missing_price | paper_eod | experimental_validation_paper.performance.reconciliation.status | EXACT | EXACT | YES |
| stale_post_close_valuation | paper_eod | experimental_validation_paper.performance.open_positions.detail[0].mark_session_classification | STALE_HISTORICAL | STALE_HISTORICAL | YES |
| stale_post_close_valuation | paper_eod | experimental_validation_paper.performance.open_positions.detail[1].mark_session_classification | POST_CLOSE | POST_CLOSE | YES |
| stale_post_close_valuation | paper_eod | experimental_validation_paper.performance.reconciliation.status | EXACT | EXACT | YES |
| recovery_affected_closed_trades | paper_eod | experimental_validation_paper.performance.closed_trades[0].recovery_affected | True | True | YES |
| recovery_affected_closed_trades | paper_eod | experimental_validation_paper.performance.closed_trades[1].recovery_affected | True | True | YES |
| recovery_affected_closed_trades | paper_eod | experimental_validation_paper.performance.closed_trades[2].recovery_affected | True | True | YES |
| recovery_affected_closed_trades | paper_eod | experimental_validation_paper.performance.closed_trades[3].recovery_affected | True | True | YES |
| reconciliation_mismatch | paper_eod | experimental_validation_paper.performance.status | UNKNOWN | UNKNOWN | YES |
| reconciliation_mismatch | paper_eod | experimental_validation_paper.performance.reconciliation.status | UNAVAILABLE | UNAVAILABLE | YES |
| reconciliation_mismatch | v2_active_strategy | ledger.performance.reconciliation.status | MISMATCH | MISMATCH | YES |
| reconciliation_mismatch | v2_active_strategy | ledger.performance.reconciliation.diff | -50407.0 | -50407.0 | YES |
