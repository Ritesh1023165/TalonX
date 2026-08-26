# Task74B Summary -- Superseding Alpha Discovery (catalyst + multi-day)

## Result: ONE candidate nominated -- PRIMARY_CANDIDATE_READY_TO_FREEZE

**CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION** (Family B, REVERSAL
hypothesis, SHORT direction) -- see `primary_candidate_draft.md`.

## Supersession

The prior Task74 design (`406910e`) was superseded BEFORE any outcome
was computed under it (confirmed by the read-only audit performed before
this task began). New design locked and pushed
(`72dcfaa`) before any Task74B outcome existed.

## Development data

Reused the existing Task71 broadened pool unchanged: 4 regime slices,
3,109,895 bars, 35 symbols + SPY, all clean. The 2026-summer slice's SPY
data was sourced from `task67a_benchmarks/SPY.csv` (already-existing
repo data for the exact same dates) since that slice's own directory
never had SPY -- documented, zero new download.

## Search: 20 predeclared cells (2 families x up to 12 cells each), reported as 40 direction-split rows for transparency (no long/short pooling)

| Family / hypothesis | Result |
|---|---|
| A -- CATALYST_EXTREME_ACTIVITY / CONTINUATION | REJECTED_COST |
| A -- CATALYST_EXTREME_ACTIVITY / REVERSAL | REJECTED_SAMPLE |
| B -- MULTIDAY_CROSS_SECTIONAL / MOMENTUM | REJECTED_NO_EDGE |
| B -- MULTIDAY_CROSS_SECTIONAL / REVERSAL / LONG | REJECTED_INSTABILITY |
| **B -- MULTIDAY_CROSS_SECTIONAL / REVERSAL / SHORT** | **PRIMARY_CANDIDATE_READY_TO_FREEZE** |
| C -- UNIVERSE_EXPANSION | UNIVERSE_EXPANSION_DEFERRED (feasibility only) |

## The winning finding

Stocks that are extreme 3-day market-adjusted cross-sectional
OUTPERFORMERS tend to mean-revert over the following 2-5 trading days.
SHORTing the top 10-20% at the next day's open produced net@10bps
+0.507% (anchor cell, 1000 trades/35 symbols/125 days), 6.07x friction
absorption, and survived every robustness check this task ran (parameter
plateau across all 6 cells, 3-of-4 regime stability, positive after
removing the 5 best trades or best 3 days). This is a materially larger
and more robust economic edge than the rejected
IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG_V1 (net@10bps +0.0005%, flipped
negative after top-3-winner removal).

Honestly disclosed weaknesses: SHORT-only (the LONG mirror is
materially weaker and unstable), one of four regimes is negative, the
EARLY development segment is weak, no stop is frozen yet, and SIP-vs-IEX
parity at the rank-threshold boundary is unverified.

## Tests

20 new focused tests (catalyst feature causality, gap/RVOL construction,
multi-day session indexing, next-session entry, cross-sectional ranking,
holdout guard, hypothesis-count enforcement) plus a 202-test broader
regression across the full Task67A/68/71/72/74/74B lineage -- all pass.

## Next

Task75 -- freeze `CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION`
(recommend the loose/3D anchor cell), design a DEVELOPMENT-only stop
from the recorded MAE/MFE diagnostics, pre-register a validation
protocol with explicit day-cluster emphasis, and lock a genuinely
untouched holdout (the reserved 2024-06-01..09-02 validation block and
2024-10-21..12-20 replication block remain available and untouched).
