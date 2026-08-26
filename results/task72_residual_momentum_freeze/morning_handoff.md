# Task72/73 Overnight -- Morning Handoff

## MORNING VERDICT: REJECTED

`IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG_V1` does **not** survive genuinely
untouched historical data after realistic costs. Final alpha status:
**RESIDUAL_MOMENTUM_V1_REJECTED**.

## Strategy frozen

- Threshold: 0.75% residual (stock 09:30->11:00 return minus causal
  trailing-20-day beta times SPY's 09:30->11:00 return)
- Horizon: 180 minutes (fixed, bounded by session close)
- Stop: 2.5% below entry (catastrophic-risk buffer, never optimized)
- Fingerprint: `f3764b6794f2e00cc5262f73d241b5274ebf544dd65cc96e7a7ab175d7c6025a`

## Holdouts

- VALIDATION: 2024-04-01..2024-05-31 -> **VALIDATION_FAIL**
- REPLICATION: 2024-10-21..2024-12-20 -> **NOT RUN** (forbidden after a FAIL)

## Validation numbers (170 trades, 35 symbols, 24 distinct days)

| Metric | Development (180m, 0.75%) | Validation |
|---|---|---|
| Gross expectancy | 0.230% | 0.101% |
| Net expectancy @10bps | 0.130% | **0.0005%** |
| Net expectancy @15bps | 0.030% | **-0.049%** |
| PF @10bps | 1.390 | 1.002 |
| Symbol-cluster CI | [0.107, 0.352] | [-0.021, 0.216] |
| Day-cluster CI | [-0.142, 0.552] | [-0.051, 0.252] |
| Top3-winners-removed expectancy | (not computed) | **-0.049%** (flips negative) |

Trade count/day count in VALIDATION dropped versus DEVELOPMENT partly
because the first ~20 trading days of the 2-month block show
`DATA_NOT_READY` (beta warmup depletion, disclosed in advance in
`holdout_exposure_audit.json` -- the deliberate choice not to download any
lead-in data outside the exact locked range).

## Main caveat / why it failed

The edge that looked real in DEVELOPMENT (net 0.130%/trade, PF 1.39,
stable across 3 regimes and 3 time segments) almost entirely evaporated at
realistic 10bps costs in an untouched holdout (net expectancy fell to
essentially zero, ~0.0005%/trade) and went negative at 15bps. Removing
just the 3 largest winning trades flips the whole holdout sample to a
negative expectancy -- the tiny surviving edge is not broad-based, it is
carried by a handful of outlier trades. Both cluster-bootstrap CIs
(symbol and day) cross zero. This is consistent with Task71's own
disclosed weakness (day-dependence) turning out to be real, not merely a
theoretical caveat -- and is exactly the kind of DEVELOPMENT-to-HOLDOUT
decay this whole overnight protocol was designed to detect honestly.

No criterion was loosened after seeing these numbers. A `classify.py`
coding bug (criterion 12 mislabeling a benign 0% stop-fire rate as a
pathology) was found and fixed, but this did not change the classification
-- criteria 3, 8, and 15 fail on economic substance regardless (see
`validation_summary.md`'s integrity note).

## Next task (exactly one, evidence-justified)

Return to Task71's forensic-reset discipline: **do not tune this
candidate's threshold/horizon/stop and re-test** (that would be exactly
the post-hoc rescue this program's own forensic audit identified as the
biggest historical failure mode). Instead, treat
`IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG_V1` as closed, and open a **fresh,
pre-registered discovery pass** on a currently-untried structural family,
using the now much larger clean-2024 inventory this task's own exposure
audit re-confirmed is still available (`2024-01-01..2024-01-31`,
`2024-03-16..2024-04-30` + `2024-06-01..2024-09-02`,
`2024-12-21..2024-12-31`, since 2024-04-01..05-31 and 2024-10-21..12-20
are now themselves consumed by this task) as genuinely fresh DEVELOPMENT
territory, rather than reusing the already-twice-picked-over
2025-01-24..2026-08-14 span again.
