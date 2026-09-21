# ORPB_V1 Architecture Rationale

## What Tasks 53-61R rule out

The evidence review was deliberately categorical, not a search over their outcomes:

- Tasks 53-58 show that mixed RSI/MACD/MA trigger/confluence economics were unstable, cost-fragile, and
  dependent on a concentrated prior winner tail. This rules out another oscillator/crossover combination.
- Task 59 concluded the shared causal/execution infrastructure was technically useful but the signal
  architecture lacked a supported economic mechanism.
- Tasks 60-61R implemented and independently rejected FPRC_V1. Its broad, interpretable sample had near-zero
  gross expectancy and negative cost-adjusted economics. This rules out tuning failed VWAP pullback/reclaim
  continuation or treating tighter cost geometry as alpha.

No Task53-61R symbol, time bucket, volatility bucket, return, winner, or threshold was used to construct ORPB.

## Why opening-range acceptance is materially different

ORPB_V1 tests whether the opening auction establishes a meaningful public boundary and whether its first
accepted upside break, accompanied by increased direct participation, represents new information being
incorporated rather than indicator-state coincidence. Its causal objects are observed price boundaries,
completed-bar acceptance, and contemporaneous traded volume—not RSI, MACD, moving-average crosses, VWAP
failure/reclaim, ATR regime membership, or optimized correlations.

The hypothesized payoff comes from continuation after price discovery. The stop and cost gate make the
hypothesis executable but cannot manufacture gross expectancy; the future protocol explicitly requires both
positive gross edge and positive 5bps edge.

## Why each fixed semantic exists

- Thirty minutes/six 5-minute bars: a complete opening price-discovery interval with a deterministic boundary.
- First close above only: tests the initial information-bearing acceptance and prevents outcome-dependent retries.
- Volume greater than the same session's opening median: requires increased participation without a fitted
  multiplier, cross-symbol normalization, or historical calibration.
- Immediate 1-minute persistence: distinguishes accepted continuation from a close that immediately reverses,
  with exactly one causal opportunity to confirm.
- Breakout-bar-low stop: invalidates the accepted-breakout event itself.
- No target: preserves the continuation payoff distribution being tested.
- Five-minute close back at/below the range: expresses thesis failure using the original public boundary.
- Cost-first capacity and 0.20R feasibility: retain operational comparability while leaving alpha semantics intact.

## Components retained from TalonX

Retained unchanged in concept: completed bars, state-only warmup, next-bar orders, long-only lifecycle, hard
stop-first ordering, 15:50 flatten, cooldown/loss lockout, capacity three, deterministic ranking/telemetry,
5bps cost-in-R, no broker, and isolated research/shadow state.

The current candidate and rejected FPRC_V1 remain untouched. ORPB_V1 is opt-in and separately namespaced.
