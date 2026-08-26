# Task74 Part 3/4 -- Research Design Lock

Declared BEFORE any new outcome is computed. See `research_design_lock.json`
for the machine-readable version.

## Families (2 of a max 3 -- deliberately fewer)

**FAMILY_A -- EXTREME_CROSS_SECTIONAL_DISLOCATION_REVERSAL**: at a late
14:00 ET decision, rank each symbol's open-to-decision return against the
other 34 universe symbols that same day (causal cross-sectional percentile
rank). An extreme dislocation that has already begun to stall in the last
30 minutes (exhaustion) is hypothesized to partially revert into the
close. SHORT the extreme winners, LONG the extreme losers.

**FAMILY_B -- VOLATILITY_EXPANSION_BREAKOUT_CONTINUATION**: at an 11:30 ET
decision, a large partial-session range (vs. a causal trailing 10-day
average full-day range) combined with a genuine break of the trailing
10-day high/low is hypothesized to CONTINUE (not fade) through the
session. LONG on breakout up, SHORT on breakdown.

Both are deliberately structurally distinct from every rejected/closed
family (F6's opening-range fade, Task71's residual momentum/AVWAP
flow-state/overnight gap/failed structural break).

## Search budget

2 families x 2 directions x 2 threshold bands x 3 horizons = **24 cells**
(cap is 36; deliberately smaller, per the task's own preference for a
tighter budget than Task71's 72).

## Promotion bar (economic-edge-first, not statistical-significance-first)

- `net_expectancy_10bps_pct >= +0.10%` per trade (primary)
- preferably positive at 15bps
- `friction_absorption_ratio >= 2.0x` at the primary cell
  (`gross_expectancy_pct / 0.10`)
- CI-excludes-zero or PF>1 ALONE is explicitly NOT sufficient.

## Robustness requirements (18 items, see JSON) and family classification
taxonomy (7 labels, no ambiguous "interesting" category) are locked
verbatim from the task specification.

## Candidate cap

At most ONE primary candidate; at most ONE research lead (only if
meaningfully close to the promotion bar).
