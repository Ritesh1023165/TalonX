# Next Alpha Discovery — Broad Development-Only Screen

Status: alpha remains **UNPROVEN**. ORPB_V1 and FPRC_V1 are rejected and retired. Task 65 validated PIV *infrastructure* only (order lifecycle, feed-mode discipline, readiness gating, reconciliation) — it produced zero canonical alpha evidence, by design. This document defines the next task: one broad, development-only discovery pass across multiple materially different alpha families, run on data disjoint from validation/replication.

## Objective

Screen several *structurally distinct* alpha hypotheses in parallel, using the same discipline that flagged ORPB_V1/FPRC_V1's problems early (economic-margin-first, no single magic threshold), so the next candidate entering validation has already survived a broader comparison — not just the first idea that looked promising in isolation.

## Candidate families (test all, not just one)

1. **Multi-hour trend continuation** — hold-through-noise continuation on an already-established multi-hour directional move, distinct from ORPB_V1's single-session opening-range breakout.
2. **15m/30m structural pullback continuation** — entry on a shallow retracement within a higher-timeframe trend, not a breakout.
3. **Volatility/range expansion** — entries triggered by a regime shift in realized range (e.g., ATR expansion off a compression base), independent of directional bias at entry.
4. **Relative-strength continuation vs. SPY/sector** — cross-sectional signal (ticker vs. benchmark), not a pure price/volume single-name signal — tests whether relative positioning adds information ORPB_V1-style single-name geometry didn't capture.
5. **Compression → expansion** — a distinct volatility-regime family from (3): explicitly requires a *prior* compression phase (e.g., narrowing range/declining volume) as a precondition, not just a same-bar ATR reading.
6. **Opening information → later-session continuation** — deliberately different from ORPB_V1: uses the opening range as an *information signal* (e.g., relative volume/direction) feeding a decision made well after the open, not an immediate breakout trigger.

Families 1/2 are trend-following variants at different timeframes; 3/5 are volatility-regime variants with and without a compression precondition; 4 is cross-sectional; 6 reuses the opening window but at a different causal distance from entry. Running all six side by side is the point — comparing structurally different mechanisms cheaply before committing validation-data budget to any one.

## Data discipline (non-negotiable, matches ORPB_V1/FPRC_V1 protocol)

| Split | Use | Rule |
|---|---|---|
| **Discovery** | Exploratory iteration across all 6 families | Iteration allowed; nothing here is held out |
| **Validation** | Confirms the surviving candidate(s) | Untouched until a family is selected from discovery |
| **Replication** | Final independent confirmation | Separate from validation, untouched until validation passes |

No family may be iterated against validation or replication data. A family that "needs" validation-data peeking to look good is a discovery-phase failure, not a validation-phase pass.

## Discovery-phase evaluation (comparative, not threshold-gated)

For each family, compare — not gate on a single number:

- **Economic margin**: gross edge vs. realistic cost burden (spread + slippage + fees), same cost-sensitivity methodology already used for ORPB_V1/FPRC_V1.
- **Opportunity frequency**: signals/week across the discovery universe — a family with real edge but near-zero frequency is not actionable at portfolio scale.
- **Cost burden**: sensitivity of net edge to cost assumptions — a family whose edge evaporates under realistic (not best-case) costs is a discovery-phase reject, same failure mode that retired ORPB_V1/FPRC_V1.
- **Winner/loss geometry**: R-multiple distribution shape, not just mean expectancy — asymmetric tails matter as much as average.
- **Symbol concentration**: whether edge is broad across the universe or concentrated in 1-2 names (concentration was a specific red flag in prior ORPB_V1 diagnostics).
- **Regime stability**: does the edge hold across different date windows/volatility regimes, or is it a single-regime artifact.
- **Stable parameter regions**: does a *range* of reasonable parameter choices work, or only an isolated best-fit point (isolated optima are the single strongest overfitting tell from prior tasks).

**No universal magic expectancy threshold.** Advance a family only if its gross economics comfortably clear realistic cost burden AND its evidence is broad/stable across symbols and regimes — both conditions, not either alone.

## Explicit non-goals for this next task

- Not alpha tuning of ORPB_V1/FPRC_V1 — both remain retired; no replay.
- Not a live/paper session — this is offline research only.
- Not a single-family deep-dive — the point is breadth first, depth only for whatever survives the comparison.
- Not a threshold-passing exercise — a family clearing an arbitrary expectancy number without broad/stable evidence is not a discovery-phase pass.

## Deliverable

A comparison report across all 6 families (economic margin, frequency, cost burden, geometry, concentration, regime stability, parameter-region stability) with a recommendation of at most 1-2 families to carry into a dedicated validation-protocol task — mirroring the Task 61/62/63 structure already used for FPRC_V1/ORPB_V1 (freeze spec → validate on held-out data → replicate).
