# Next Candidate Specification

## Status and boundary

Specification only. Task 59 does not implement, replay, tune, or authorize this candidate. The architecture
name is `FAILED_PULLBACK_RECLAIM_CONTINUATION_V1` (`FPRC_V1`). It is one indivisible candidate, not a menu
of variants. Tasks 53–58 motivate abandoning the current architecture but must not be used to calibrate
FPRC_V1 parameters or select among alternatives.

## Economic hypothesis

In a liquid stock already in an established intraday/higher-timeframe uptrend, a short-lived break below
regular-session VWAP followed by an immediate reclaim and one-bar price persistence represents a failed
pullback: transient supply has been absorbed and continuation buyers should produce favorable excursion
large enough to exceed structural risk and realistic execution friction.

This is a conditional continuation hypothesis, not a claim that RSI, MACD, relative volume, trend alignment,
or volatility alone predicts returns.

## Signal semantics

All state uses completed bars and America/New_York regular-session data.

1. **Direction and session:** long-only; the existing 09:30–09:45 and 15:30–16:00 ET entry blackouts apply.
2. **Trend context:** the latest price and latest completed 15m close must be above the existing 15m SMA200.
   The SMA200 must be non-declining versus its value four completed 15m bars earlier. Four bars is one hour
   and is frozen here for semantic direction confirmation, not selected from Tasks 53–58.
3. **Pullback state:** after the opening blackout, at least two consecutive completed 1m bars must close below
   regular-session VWAP while the trend context remains valid. The setup-local low is the minimum low from the
   first below-VWAP bar through the reclaim bar.
4. **Reclaim trigger:** the first completed 1m bar whose previous close is at/below VWAP and whose current close
   is above both VWAP and the previous bar's high creates a trigger state. A later reclaim is a new setup only
   after the current state resets.
5. **State reset:** reset without a trade if trend context fails, the session enters the closing blackout, or
   the immediately following confirmation bar fails.

RSI14, MACD(12,26,9), SMA(10,50), relative volume, and the existing 15m/60m ATR-regime readings are recorded
for observability only. They do not trigger, confirm, rank, or reject FPRC_V1.

## Confirmation semantics

Confirmation is sequential and price-based. The single 1m bar immediately following the reclaim trigger must:

- close above VWAP;
- close above the reclaim trigger bar's high; and
- leave the 15m trend context valid.

No same-bar indicator can confirm its own trigger. There is no three-bar grace period, alternative confirmation,
or confirmation score. If the next bar fails, the setup expires. A passing confirmation publishes one candidate;
entry occurs at the next 1m bar open under the existing causal fill convention.

## Volatility and trend roles

- The 15m SMA200 is directional context and readiness state, not claimed alpha.
- The existing 0.329% 15m and 0.839% 60m ATR thresholds are removed from eligibility and retained as telemetry.
- Volatility enters eligibility only through observable trade geometry and cost burden: a setup too tight to
  absorb the frozen cost assumption is rejected before publication.
- No volatility expansion label, RSI regime, symbol-specific rule, or market-regime classifier is introduced.

## Stop, target, and exit philosophy

- **Initial stop:** one minimum price tick below the setup-local pullback low. This is the exact invalidation of
  the failed-pullback thesis; prior-session S1 and ATR fallback are not used for FPRC_V1.
- **Geometry validity:** require `stop < expected entry reference`; zero/non-finite risk fails closed.
- **Profit target:** none. A fixed target would cap the continuation tail the hypothesis is intended to test.
- **Hypothesis-failure exit:** the first completed 5m bar closing below regular-session VWAP schedules an exit
  at the next available 1m bar open.
- **Hard-risk exit:** the fixed initial stop remains active intrabar from the entry bar onward; no break-even
  move, trailing stop, partial exit, or discretionary override.
- **Session exit:** the existing 15:50 ET `END_OF_SESSION` flatten remains mandatory. No overnight holding.
- RSI/MACD/MA events do not close FPRC_V1 positions.

## Cost-aware feasibility and minimum edge

At candidate revalidation, compute frozen 5bps round-trip cost in R from the expected entry reference and
setup-local stop:

`estimated_cost_R_5bps = (entry * 0.0005 + entry * 0.0005) / abs(entry - stop)`

The setup is eligible only when `estimated_cost_R_5bps <= 0.20R`. The same calculation is repeated against
the actual next-bar fill; a fill above `0.20R` cost burden is rejected. The 0.20R ceiling is an ex-ante risk
budget: at most one fifth of initial risk may be consumed by the frozen friction assumption. It is not inferred
from a Task 53–58 bucket.

The architecture-level minimum required edge is stronger: on independent validation, mean gross expectancy
must exceed observed mean 5bps cost burden by at least `0.15R/trade`, mean 5bps net expectancy must be at least
`+0.15R/trade`, and its 95% bootstrap lower bound must exceed zero. Lower assumed costs may be reported but
cannot qualify the candidate.

## Capacity and ranking

The existing maximum-three release capacity remains. If more than three FPRC_V1 candidates confirm together,
rank by:

1. lowest actual-reference `estimated_cost_R_5bps`;
2. earliest confirmation timestamp; then
3. ticker ascending as a deterministic tie-break.

The current composite confluence/R:R/volume/trend score is not used. Capacity ranking is operational, not an
edge claim.

## What remains unchanged

- 35-symbol universe and Alpaca-only historical provider;
- long-only positions and one open position per symbol;
- causal 10-trading-day state-only pre-roll and mandatory readiness/data-quality gates;
- completed-bar inputs, next-bar-open entry, conservative same-bar stop-first resolution;
- regular-session blackouts, 20-minute cooldown, 75-minute post-loss lockout, maximum-three capacity;
- 15:50 ET flatten, zero overnight exposure;
- 0bps and 5bps reporting, MFE/MAE, cost-in-R, provenance, and deterministic artifacts;
- `MONDAY_DECISION_SHADOW_ONLY`, no capital, and no production change.

## What must change before any future replay

- replace three indicator-family triggers with the single failed-pullback/reclaim state machine;
- replace same-bar indicator confirmation with the next-bar persistence contract;
- add causal regular-session VWAP and setup-local pullback state;
- replace prior-session pivot/ATR stop and target/R:R screen with setup-local invalidation and cost feasibility;
- replace generic opposite-family exits with the VWAP hypothesis-failure exit;
- remove hard 15m/60m ATR thresholds from eligibility;
- replace composite opportunity ranking for this candidate with deterministic cost-first ordering;
- namespace all FPRC_V1 state and telemetry so it cannot affect the current shadow candidate.

No part of this specification authorizes implementation. Implementation, if separately approved, must be
completed and frozen before the independent protocol is run.
