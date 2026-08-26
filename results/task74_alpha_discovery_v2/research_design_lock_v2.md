# Task74B -- Superseding Research Design Lock

Declared BEFORE any new outcome is computed. See `research_design_lock_v2.json`.

## Families (3, materially different from every prior/rejected family)

**FAMILY_A -- CATALYST_EXTREME_ACTIVITY**: 10:00 ET decision. Combined
overnight-gap-magnitude + relative-volume (RVOL) trigger; CONTINUATION and
REVERSAL hypotheses tested separately. RVOL is volume-based ->
PROVIDER_SENSITIVE. 8 cells.

**FAMILY_B -- MULTIDAY_CROSS_SECTIONAL** (highest priority): Day0-close
market-adjusted 3-day cross-sectional rank; MOMENTUM and REVERSAL
hypotheses tested separately; Day1 open entry; 2/3/5-trading-day exits.
No stop (fixed-horizon discovery first). 12 cells.

**FAMILY_C -- UNIVERSE_EXPANSION_FEASIBILITY**: feasibility study only,
0 outcome cells pending the finding in `universe_expansion_feasibility.json`.

## Search budget: 20 cells (cap 36) -- fewer than the superseded design's 24.

## Promotion bar (stricter than Task74's superseded design)

- `net_expectancy_10bps_pct >= +0.15%`
- preferably `net_expectancy_15bps_pct >= +0.10%`
- positive (or close to it) at 20bps
- `friction_absorption_ratio >= 2.5x` at the primary cell

## Development data

Reuses the existing Task71 broadened pool unchanged (35 symbols + SPY, 4
slices). No new download. No pre-roll beyond the small K=3-day lookback
already inherent to Family B's mechanism (accepted warmup depletion,
same precedent as Task71).
