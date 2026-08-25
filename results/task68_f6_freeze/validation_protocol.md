# F6_FADE_V1 — Pre-Registered Validation Protocol (for Task 69)

Declared BEFORE any validation outcome is known. Machine-readable version: `validation_protocol.json`.

## Input
- Strategy: `F6_FADE_V1`, required fingerprint `6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084` — Task 69 must verify this matches before running anything.
- Dataset role: `UNSEEN_HOLDOUT` = the already-reserved VALIDATION window (2026-08-25→2026-09-22, per `data_split_contract.json`), materialized only once it has fully traded (not before 2026-09-23).
- Fields: symbol/timestamp/open/high/low/close/volume. Provider: Alpaca historical SIP. ~20–40 trading days, 35-symbol universe where quality permits.

## Output (Task 69 must produce)
`number_of_candidates`, `number_of_trades`, `symbol_coverage`, `session_coverage`, `gross_expectancy`, `net_expectancy_primary_cost`, `profit_factor`, `result_0bps`/`result_5bps`/`result_10bps`, `bootstrap_ci`, `win_rate`, `average_win`, `average_loss`, `max_drawdown`, `top1_symbol_contribution`, `top3_symbol_contribution`, `top1_day_contribution`, `top3_winners_removed_expectancy`, `MFE`, `MAE`, `missing_data_exclusions`, `strategy_fingerprint_match`, `dataset_hash`, `classification`.

## Pass logic (fixed now, not adjustable after seeing results)

**VALIDATION_PASS** requires ALL 8:
1. Net expectancy positive at the frozen 10bps primary cost.
2. Gross effect direction matches the fade hypothesis.
3. No one-symbol/one-day domination (≤40% each).
4. Removing the top-3 winners doesn't completely destroy the result.
5. Enough trades/breadth to interpret (≥30 trades, ≥10 symbols, ≥10 days).
6. Bootstrap CI not grossly inconsistent with a positive edge.
7. Realistic costs (5–10bps) don't erase essentially all edge.
8. No causal/data-integrity violation (fingerprint match, no synthetic data, causal timestamps).

**VALIDATION_FAIL**: evidence materially contradicts the frozen hypothesis (negative net edge AND inconsistent gross direction, or an integrity violation).

**VALIDATION_INCONCLUSIVE**: sample size/uncertainty prevents a credible decision — not the same as FAIL.

**Replication is forbidden unless the classification is exactly VALIDATION_PASS.** No re-litigating the criteria after seeing the numbers.
