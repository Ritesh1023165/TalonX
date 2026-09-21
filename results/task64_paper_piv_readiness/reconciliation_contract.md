# Reconciliation Contract

Preflight queries paper orders and positions and compares broker position symbols with persisted internal open-position symbols. Any mismatch blocks readiness. Restart reloads persisted intents/orders/positions and retains duplicate protection.

EOD disables entries, cancels residual PAPER orders, requests PAPER position closure, reconciles, and writes `latest_reconciliation.json` plus `latest_session_report.json`. Reports cover data health, readiness events, signals, rejections, intents, submissions, accepts/rejects, fills, positions, unexpected/missed orders, duplicate prevention, Telegram status, reconciliation, and P&L/R fields when available. Anomalies use only: `PARITY_OK`, `ENGINE_DEFECT`, `DATA_ISSUE`, `EXECUTION_DRIFT`, `STRATEGY_BEHAVIOR_EXPECTED`, or `REVIEW_REQUIRED`.
