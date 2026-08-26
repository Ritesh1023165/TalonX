# Task74B -- Candidate Ranking

**Promotion bar:** net@10bps >= +0.15%, preferably net@15bps >= +0.10%,
friction_absorption_ratio >= 2.5x.

## PRIMARY_CANDIDATE_READY_TO_FREEZE

**FAMILY_B_MULTIDAY, hypothesis=REVERSAL, direction=SHORT** (extreme
past 3-day cross-sectional WINNERS, bet SHORT for multi-day reversion).

All 6 cells (2 bands x 3 horizons) share the SAME positive sign -- a
genuine plateau, not an isolated peak:

| Band | Horizon | Trades | Symbols | Days | Gross | Net@10bps | PF@10bps |
|---|---|---|---|---|---|---|---|
| loose | 2D | 1032 | 35 | 129 | 0.182% | 0.082% | 1.056 |
| loose | 3D | 1000 | 35 | 125 | 0.607% | **0.507%** | 1.305 |
| loose | 5D | 936 | 35 | 117 | 0.806% | 0.706% | 1.305 |
| tight | 2D | 516 | 35 | 129 | 0.256% | 0.156% | 1.105 |
| tight | 3D | 500 | 35 | 125 | 0.679% | 0.579% | 1.338 |
| tight | 5D | 468 | 35 | 117 | 0.745% | 0.645% | 1.262 |

**Recommended anchor cell: loose/3D** -- the only cell where BOTH the
symbol-cluster CI [0.068, 1.271] AND the day-cluster CI [0.034, 1.201]
exclude zero (loose/5D and tight/5D have larger raw edges but their
day-cluster CIs cross zero).

- Net@15bps: +0.457%, Net@20bps: +0.407% -- edge survives comfortably
  at every cost level tested.
- Outlier robustness: removing the 5 best trades still leaves net@10bps
  at +0.129%; removing the best 3 days still leaves +0.223%. **Never
  flips negative** -- materially more robust than the rejected
  residual-momentum candidate, which did flip negative under the same
  test.
- Concentration: top1 symbol 12.3%, top3 symbols 28.3%, top1 day 4.9%
  -- all comfortably under the 30% caps.
- Regime stability: 3 of 4 development regimes positive; 2025 Q3 (FPRC
  era) is negative (-0.69%) -- disclosed, not hidden.
- Time-segment stability: EARLY slightly negative (-0.04%), MIDDLE
  (+0.79%) and LATE (+0.78%) strongly positive.
- **Asymmetry, disclosed honestly:** the mirror LONG side (extreme
  LOSERS reverting up) is materially weaker -- sign flips at 2D, and
  NEITHER cluster CI ever excludes zero across its 6 cells. This is a
  **SHORT-ONLY** finding.

## Everything else: REJECTED

| Family / hypothesis / direction | Classification | Reason |
|---|---|---|
| FAMILY_B REVERSAL / LONG | REJECTED_INSTABILITY | Sign flips at 2D; no cluster CI ever excludes zero |
| FAMILY_B MOMENTUM / both | REJECTED_NO_EDGE | Negative in all 12 cells |
| FAMILY_A CONTINUATION / both | REJECTED_COST | Larger loose-band sample net-negative after cost; tight-band's small positive too thin (n=25) to corroborate |
| FAMILY_A REVERSAL / both | REJECTED_SAMPLE | Attractive point estimates but n=25-48, both cluster CIs cross zero at every cell, 3-8 trades per regime |
| FAMILY_C universe expansion | UNIVERSE_EXPANSION_DEFERRED | No defensible point-in-time universe data source exists |

**Research lead recorded: NO** -- no remaining direction is meaningfully
close to promotion once sample size and cluster-CI evidence are weighed
honestly; recording one would repeat the small-sample-overfitting
pattern this program's own forensic audit already diagnosed as its
biggest historical failure mode.
