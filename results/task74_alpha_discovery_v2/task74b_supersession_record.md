# Task74B -- Supersession Record

**Previous design commit:** `406910e7bab4724fe80fa75f0c2cd7db86fb7515`
(TASK74_RESEARCH_DESIGN_LOCK -- 2 families, cross-sectional dislocation
reversal + volatility-expansion breakout continuation)

**Outcomes computed under old design: NONE.** The only execution attempt
of `research/scripts/task74_run_discovery.py` crashed at import time
before any data loading or evaluation. Zero cell results, expectancy, PF,
or win-rate values were ever computed, printed, or inspected.

**Reason for supersession:** external methodological review motivated a
pivot toward catalyst/extreme-activity setups, multi-day holding
horizons, and feasibility-only study of a higher-volatility universe --
motivated by the repeated pattern (most recently
RESIDUAL_MOMENTUM_V1: gross +0.1005%, net@10bps +0.0005%, net@15bps
-0.0495%, PF@10bps 1.0018, negative after top-3-winner removal) of
ordinary mega-cap intraday effects having gross expectancy too close to
realistic friction.

**Holdout: unchanged and preserved.** Reserved validation
(2024-06-01..09-02) and reserved replication (2024-10-21..12-20) blocks
remain untouched; `holdout_budget_audit.json` is unmodified since its
original commit.

## Old Task74 source code disposition (Part 9)

| File | Classification |
|---|---|
| `holdout_guard.py` | REUSE_UNCHANGED |
| `features.py` | DISCARD (deleted) |
| `family_a.py` | DISCARD (deleted) |
| `family_b.py` | DISCARD (deleted) |
| `research/scripts/task74_run_discovery.py` | DISCARD (deleted) |
| `test_task74_{features,family_a,family_b,search_budget}.py` | DISCARD (deleted) |
| `test_task74_holdout_guard.py` | REUSE_UNCHANGED |

Synthetic-test execution against the deleted mechanism files does not
constitute outcome exposure -- none of it touched real DEVELOPMENT data.
