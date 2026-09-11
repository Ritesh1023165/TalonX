# Task 74S — Stage 4: Economics and Robustness

## Primary result
**N/A.** `trades_executed = 0` across all 10 symbols and the entire ~1-year window. Per this task's
own preregistered decision gate (`preregistration.json::decision_gates.zero_trades`): economics are
reported as N/A, and profitability is classified `INCONCLUSIVE` — not negative, not positive, not
validated. No P&L, R-multiple, win rate, profit factor, expectancy, drawdown, or bootstrap confidence
interval can be computed from an empty trade population; none is fabricated.

## Secondary cost-sensitivity grid (zero/half/baseline/double)
**N/A for the same reason.** The preregistered analytic-recomputation method (`evaluation_protocol.md`
§6) reapplies `apply_entry_cost`/`apply_exit_cost` to each trade's raw entry/exit prices — with zero
trades, there is nothing to recompute. This is not a gap in the method; it is the correct, disclosed
consequence of a zero-trade primary result. No additional `BacktestEngine` passes were run to "search"
for trades under looser cost assumptions — cost sensitivity does not affect trade *identification*
(Stage 1 preregistration already established this from `execution.py` directly), so a friendlier cost
assumption could not have produced a trade here regardless.

## Robustness / concentration observations (qualitative — no economics to test for dependence)
- **No sample-size threshold applies** — there is no sample. Per the preregistered commitment, no
  post-hoc threshold is invented to describe this as "just below" or "close to" adequate.
- **Symbol concentration of raw candidate volume is real but immaterial to the outcome**: STX (1,994
  candidates) and AMD (1,242) account for 45% of all raw candidates system-wide, yet are rejected at
  materially the same `LOW_CONFLUENCE`-dominated rate as the quietest symbol (AAPL, 71 candidates,
  same dominant rejection reason). Higher raw signal volume in 2 of 10 symbols does not translate into
  eligible setups — this is evidence the bottleneck is structural (confluence/volatility gate
  interaction), not a data-availability or symbol-selection artifact.
- **Temporal concentration**: candidate volume varies 14x across calendar-month buckets (63 in the
  2025-08 partial bucket vs. 896 in 2026-07), yet zero buckets produce a trade. The bottleneck is
  stable across the full year, not confined to a single regime window (consistent with, and now much
  better powered than, Task 73S's single-window AAPL finding).
- **Zero-short invariant holds trivially** (no trades of any direction were opened) — nothing to
  qualify further.
- **Correlated-trade caveat is moot**: with zero trades there are no correlated observations to
  mis-treat as independent.
- **Portfolio-level statistics**: not applicable/not reported — this harness models trade-level
  R-multiples only (concurrency, sizing, capital, and overlapping positions are not modelled; see the
  CLI's own `portfolio_disclaimer` in `stage3_replay/task74s_10symbol_full_summary.json`), and there
  are zero trades to aggregate at any level regardless.

## Runner changes
None. `talonx_backtest` was invoked exactly as documented in `stage3_replay_launch_manifest.json`, no
CLI or engine code was modified to obtain or interpret this result.

**Stage 4 verdict: COMPLETE. Economics: N/A. Profitability verdict: INCONCLUSIVE.**
