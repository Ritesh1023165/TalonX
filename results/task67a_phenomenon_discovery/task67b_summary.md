# Task 67B — Stage 1 Phenomenon Discovery: Final Decision

All 6 preregistered families were screened end-to-end on DEVELOPMENT data (35 symbols, 2026-05-15→2026-08-14) using the shared, tested toolkit (`research/task67a_lib/{research_stats,screening_framework,family_runner}.py`). VALIDATION and REPLICATION data remain untouched and unmaterialized.

## Verdict table

| Family | Rollup (3 defs) | Headline |
|---|---|---|
| F1 Multi-Hour Trend | 0 PRESENT / 3 WEAK / 0 NOT_OBS | Mild mean-reversion, not continuation; economically trivial |
| F2 Structural Pullback | 0 PRESENT / 3 WEAK / 0 NOT_OBS | Excess sign often opposite the hypothesis; unstable effect surface |
| F3 Range Expansion | 0 PRESENT / 1 WEAK / 2 NOT_OBS | One promising-looking cell (n=76, unstable) — not corroborated |
| F4 Relative Strength | 0 PRESENT / 3 WEAK / 0 NOT_OBS | Beta-adjusted signal real (CI excludes 0) but too small vs. friction |
| F5 Compression→Expansion | 0 PRESENT / 0 WEAK / 3 NOT_OBS | Clean negative: compression alone predicts nothing |
| **F6 Opening→Later** | **3 PRESENT / 0 WEAK / 0 NOT_OBS** | **The standout — see below** |

Full per-family numbers: `family_comparison.csv`, `cross_family_summary.md`. Ranking (composite score, method fixed before results were inspected): F6 (17.9) ≫ F3 (14.0) > F2 (12.9) > F4 (12.4) > F1 (11.0) > F5 (7.9).

## The finding that matters: Family 6, and it's a REVERSAL not a continuation

Family 6 was originally framed as "opening information → later-session **continuation**." All three of its independently-defined signals (opening return magnitude, opening relative strength vs. SPY, opening relative volume) instead show a coherent **fade/mean-reversion** effect: strong opening-30-minute moves predict *negative* excess return (vs. matched, no-signal controls) into the rest of the session, consistent in sign across 15/30/60/120-minute horizons, with the 95% clustered-bootstrap CI excluding zero at 15m, 60m, and 120m. Economics classify as `POTENTIALLY_TRADEABLE` (excess ~0.08–0.17% vs. a 10bps round-trip friction reference), breadth is full (35/35 symbols, 63/63 days), concentration is low (top symbol ≤9.3% of positive effect), and the effect surface is stable (not a single-cell spike) — the only family to clear every element of the `PHENOMENON_PRESENT` bar on all three of its definitions.

**Anyone building on this must fade the open, not follow it.** That reframing is the single most important thing this task found.

## What was explicitly NOT nominated

`family_03_range_expansion`'s `compression90_expansion10_2.5x` definition looked attractive in isolation (60m excess +0.26%, CI excludes zero, STRONG_EFFECT-classified), but it's one definition out of three (the other two were `PHENOMENON_NOT_OBSERVED`), on only 76 events (`LIMITED` data sufficiency), with `EFFECT_SURFACE_INSTABILITY=True` — exactly the "isolated best-fit point" pattern this whole methodology exists to catch, not chase. It's recorded as a watch item, not carried into Stage 2.

## Stage 1 Decision

**PHENOMENON_READY_FOR_STAGE_2** — nominate **Family 6 (opening information → later-session, reframed as reversal) only**. Full detail on what a Stage 2 spec would need to freeze (signal choice, decision timestamp, holding horizon, realistic cost model, and the validation protocol against the still-untouched VALIDATION window) is in `task67b_summary.json`'s `candidates_nominated` block.

Stage 2 is **not started**. No trade-rule code was written. Alpha status remains **UNPROVEN** — this is a DEVELOPMENT-data screening result, not a validated edge.

See `claude_handoff_next.md` for a fully standalone continuation brief.
