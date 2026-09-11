# Stage 3 -- Next Research Plan

This overnight task ran ONE development-period regime
(`range_chop_2025`, clipped to 2025-08-15..2025-12-31 by data
availability) on a 3-symbol subset (AAPL, MSFT, NVDA) of the 10 symbols
already downloaded in `data/historical_1m/task7b_alpaca_long_history`.
This is a scope-limited overnight run, not a complete validation.

## Recommended follow-up (in order)

1. **Full 10-symbol run of the same regime** -- extend from the 3-symbol
   subset to the full available universe in
   `task7b_alpaca_long_history`, same DEVELOPMENT period, same frozen
   candidate, same cost assumption.
2. **A genuine, separate VALIDATION-period run** -- using
   `data/historical_1m/task46_validation_windows` or
   `task54_extended_windows` (not inspected this task; contents/date
   ranges unknown, need auditing first) -- per this task's own
   preregistration, VALIDATED_AND_REPLICATED was definitionally
   unreachable this task since no validation run was performed.
3. **Do not touch `task56_holdout`/`task56_independent_family_holdout`**
   until a candidate + full decision-gate preregistration exists
   specifically for that data (per this task's own untouched-holdout
   discipline).
4. **Stage 2's fixture recalibration** (see `stage2_root_cause.md`) --
   `examples/data/sample_AAPL_trade_1m.csv` needs a same-bar MACD cross
   added near its target RSI-recovery/volume-surge candidate so it
   clears `confluence_score_min=2` under the current (correctly
   confirmed) strategy rules.
5. If Stage 3's development-period numbers look promising, a dedicated
   task should independently re-verify: outlier sensitivity, symbol
   concentration, and window/regime concentration BEFORE ever
   proceeding to a validation-period run -- exactly this task's own
   decision-gate order.
