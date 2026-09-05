# Task 59 — Current Candidate Final Triage + Next Architecture Specification

**Decision:** `REDESIGN_SIGNAL_ARCHITECTURE`

**Deployment:** `MONDAY_DECISION_SHADOW_ONLY`

Task 59 is a read-only synthesis of Tasks 53–58 and repository code. It performs no correlation mining,
threshold search, parameter sweep, market-data download, strategy replay, implementation, or production change.

## Current candidate verdict

The experimental candidate is technically coherent and reproducible, but economically unsupported as a
deployable architecture: frequency is adequate, yet combined gross expectancy is weak, 5bps economics are
decisively negative, MACD is gross-negative, MA is inactive, and RSI's apparent prior edge does not survive
the independent payoff regime without a concentrated winner tail.

This is not `RETAIN_CURRENT_ARCHITECTURE`: the complete candidate fails absolute economics. It is not
`RETAIN_RSI_RESEARCH_ONLY`: RSI can remain observational context, but Task56/58 do not support preserving
the RSI curl as the next entry architecture. It is not yet `RETIRE_CANDIDATE`: the causal infrastructure and
a coherent continuation clue justify one genuinely new, tightly preregistered architecture rather than another
iteration of the current trigger/threshold stack.

## Final evidence synthesis

- **Task 53:** causal pre-roll fixed readiness/frequency, but 34 trades were only +0.012R/trade gross and
  -0.333R/trade at 5bps.
- **Task 54:** 89 trades across 22 symbols were +0.237R/trade gross but -0.292R/trade at 5bps; uncertainty
  still included zero.
- **Task 55:** RSI exceeded MACD in the prior sample, but the family result was explicitly tentative and
  winner-tail sensitive.
- **Task 56:** the independent 105-trade holdout passed its interpretability floor. RSI weakened to +0.016R
  gross/-0.240R at 5bps; MACD was -0.021R/-0.427R; common-support and top-winner robustness failed.
- **Task 57:** all 228 trades produced +0.092R/trade gross/PF 1.150 versus -0.324R/trade/PF 0.659 at 5bps.
  Mean/median cost burden was 0.416R/0.252R, and removing extreme-cost trades did not restore broad health.
- **Task 58:** prior RSI expectancy of +0.621R fell to +0.058R after removing three winners. Task56 retained
  the win rate but lost payoff magnitude: winner MFE fell 4.240R to 2.200R while capture stayed near 0.71.
  No stable pre-entry HTF/volatility separator reproduced across Tasks53, 54, and 56.

## Current pipeline trace and unsupported assumptions

1. Deduplicated 1m bars feed causal 1m, completed 15m, and completed 60m state after warmup.
2. RSI14, MACD(12,26,9), SMA(10,50), ATR14, volume, pivots, SMA200, and regime state are computed.
3. The experimental 15m/60m ATR gate (0.329%/0.839%) rejects before trigger evaluation.
4. Edge-triggered RSI curl, MACD crossover, and MA crossover events share the same candidate object.
5. The engine applies session/blackout, cooldown/loss-lockout, at-least-one independent same-bar confirmation,
   pivot R:R >=1.5, 15m SMA200 alignment, and pre-market fail-closed gates.
6. Survivors are ranked by a composite confirmation/R:R/volume/trend score, capped at three, revalidated, and
   entered next bar. Fill-invalid geometry is repaired or rejected.
7. A hard stop/target bracket, generic opposite-family signal, 15:50 flatten, or data end closes the position.

The code correctly implements that contract. The unsupported architectural assumptions are economic: that
three heterogeneous triggers can share one confirmation/geometry/exit model; that one same-bar independent
condition validates continuation; that accepted ATR depth or SMA alignment discriminates winners; that
prior-session pivot R:R predicts realized payoff; that the composite score ranks edge; and that generic
opposite-indicator exits express the failure of each entry thesis. Tasks53–58 do not support those claims.

## Keep, change, and drop

**Keep:** causal pre-roll/readiness, closed-bar evaluation, next-bar fills, long-only state handling, data-quality
gates, session blackouts, cooldown/loss-lockout/capacity controls, fill-time geometry validation, conservative
stop-first handling, 15:50 flatten, cost/MFE/MAE telemetry, and deterministic provenance. Keep 15m SMA200 only
as directional context—not as proven alpha.

**Change:** replace the mixed-family trigger stack with one hypothesis-specific state machine; make confirmation
sequential and price-based; make the stop the local thesis invalidation; make exits express thesis failure;
replace hard ATR-regime eligibility with actual cost-in-R feasibility; and remove unvalidated composite-alpha
ranking.

**Drop from next-candidate eligibility:** RSI, MACD, and MA as entry triggers; same-bar indicator confirmation;
prior-session pivot target/R:R screening; hard 15m/60m ATR thresholds; and opposite-family exits. The indicators
may remain telemetry so implementation can be audited without turning them into hidden filters.

## One next architecture

`FAILED_PULLBACK_RECLAIM_CONTINUATION_V1` tests one hypothesis: in an established uptrend, a brief break below
regular-session VWAP followed by an immediate reclaim and next-bar persistence identifies absorbed supply and
enough continuation to clear structural risk and 5bps friction.

The exact state machine, setup-local stop, VWAP-failure exit, cost ceiling, unchanged controls, and prohibited
variants are frozen in `next_candidate_spec.md`. The candidate is not implemented or replayed here.

## Preregistered evaluation and hard stop

Use the first 60 complete XNYS trading days after 2026-07-09 as three consecutive 20-day windows with causal
10-day pre-roll, all 35 symbols, Alpaca only, one frozen candidate, and 0bps/5bps reporting. It must clear the
support floor, >=+0.15R 5bps expectancy, PF >=1.25, positive 95% bootstrap lower bound, window breadth, top-winner
and concentration controls, and <=0.20R actual-fill cost burden.

Failure of any mandatory criterion after outcomes are unblinded retires FPRC_V1. No parameter adjustment,
sample extension, gate change, or variant replay is allowed on those windows. A pass requires a second untouched
60-day replication and still does not authorize production.

No capital or production action is authorized. Monday remains shadow-only.
