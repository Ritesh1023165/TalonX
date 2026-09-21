# ORPB_V1 Candidate Specification

## Status and boundary

`OPENING_RANGE_PARTICIPATION_BREAKOUT_V1` (`ORPB_V1`) is one indivisible, long-only research/shadow
candidate. It is not imported by or connected to the current TalonX candidate. Task 62 freezes its contract
but performs no historical signal generation, replay, return calculation, or validation.

Tasks 53-61R are used only to exclude failed architectural classes. They do not select an ORPB threshold,
symbol, time bucket, stop, or exit. ORPB_V1 is not an RSI/MACD/MA crossover or confluence variant and does
not use a failed VWAP pullback/reclaim.

## Economic hypothesis

The first 30 regular-session minutes form an auction-derived price-discovery range; the first completed
5-minute close above that range on participation strictly greater than the opening-range 5-minute median,
followed immediately by 1-minute price persistence, identifies information-driven demand whose continuation
can produce positive gross expectancy after breakout-local invalidation and realistic execution friction.

The hypothesized alpha is continuation after a price-discovery boundary is accepted with increased direct
market participation. Cost feasibility protects tradability but is not the proposed source of edge.

## Frozen setup and trigger

All decisions use completed America/New_York regular-session bars.

1. Build the opening range from exactly the first six completed 5-minute bars, 09:30-09:59 ET. Its high and
   low are the extrema of those bars. Its participation baseline is the median of their six total volumes.
2. Starting with the 10:00-10:04 bar, observe the first completed 5-minute bar whose close is strictly above
   the opening-range high. This is the session's only breakout attempt.
3. The breakout triggers only if its total volume is strictly greater than the frozen opening median. Equal
   volume does not pass. A low-volume first breakout exhausts the session; a later breakout cannot retry.
4. RSI, MACD, MA, ATR, VWAP, relative-volume adapters, and any external telemetry do not trigger, confirm,
   rank, reject, or exit ORPB_V1.

The 30-minute range represents the opening auction/price-discovery interval. Completed 5-minute acceptance
reduces sensitivity to a single 1-minute print. Comparing volume to the session's own six-bar median avoids a
calibrated multiplier or symbol-specific baseline. These semantics were chosen from market microstructure
reasoning before any ORPB historical outcome was read.

## Frozen confirmation

The single completed 1-minute bar immediately following the breakout bar must close strictly above the
breakout bar's high. The confirmation must pass the existing entry blackout. There is no grace period,
confirmation score, alternative confirmer, or same-bar confirmation. A passing close publishes one candidate;
entry occurs at that symbol's next available 1-minute bar open.

If immediate confirmation fails, the session attempt is exhausted. A later close cannot revive it.

## Frozen invalidation and execution

- Initial stop: exactly one minimum tick (`$0.01`) below the completed breakout 5-minute bar's low.
- Geometry: stop must be finite and strictly below the expected/actual entry.
- Profit target: none. A fixed target would cap the continuation payoff the hypothesis is intended to test.
- Thesis failure: the first completed post-opening 5-minute bar closing at or below the opening-range high
  while a position is open schedules an exit at the next available 1-minute bar open.
- Hard stop: active intrabar from the entry bar; stop-first handling wins any same-bar ambiguity.
- Session exit: mandatory `END_OF_SESSION` close at or after 15:50 ET; no overnight exposure.
- No trailing stop, break-even move, partial exit, indicator exit, discretionary override, or re-entry.

## Frozen cost feasibility

The provider/fill contract reports 0bps and 5bps per side on identical trades. Before publication:

`estimated_cost_R_5bps = (entry_reference * 0.0005 * 2) / abs(entry_reference - stop)`

The candidate passes only when this is finite and `<= 0.20R`. The same two-sided estimate is recomputed at
the actual next-bar fill and must remain `<= 0.20R`. Net reporting uses actual entry and exit notionals:

`actual_cost_R_5bps = (entry * 0.0005 + exit * 0.0005) / abs(entry - stop)`

The 0.20R ceiling is a frozen tradability constraint, not the alpha thesis and not a Task53-61R-derived
filter.

## Frozen safety and ranking

- Exact 35-symbol universe in `freeze_manifest.json`; no symbol-specific behavior.
- Long only; one open/pending position per symbol.
- Maximum three simultaneous released opportunities.
- Cost-first deterministic ranking: lowest estimated cost-in-R, then earliest confirmation, then ticker.
- Existing 20-minute cooldown and 75-minute post-loss lockout.
- Existing regular-session entry blackouts and 15:50 flatten.
- Causal state-only warmup, completed-bar processing, next-bar fills, deterministic telemetry, and no broker.

## Reset and rejection contract

- New regular-session date resets opening range, attempt, and trigger state.
- Missing/nonregular bars never create a trigger.
- An incomplete six-bar opening range never arms the candidate.
- The first above-range 5-minute close consumes the sole session attempt.
- Insufficient participation rejects as `PARTICIPATION_INSUFFICIENT`.
- Entry blackout rejects as `ENTRY_BLACKOUT`.
- Failed immediate persistence expires as `IMMEDIATE_CONFIRMATION_FAILED`.
- Invalid/tight estimated geometry rejects as `ESTIMATED_COST_OR_GEOMETRY_INFEASIBLE`.
- Invalid/tight actual fill rejects as `ACTUAL_FILL_COST_OR_GEOMETRY_INFEASIBLE`.
- Existing position, pending entry, cooldown, post-loss lockout, capacity, or prior flatten rejects fail closed.

## Anti-iteration rule

ORPB_V1 has no authorized variants. Failure of any mandatory criterion on its frozen validation sample retires
the candidate. The sample cannot be extended, replayed with a different rule, or mined for a filter, symbol,
time bucket, parameter, stop, target, cost, or second attempt.
