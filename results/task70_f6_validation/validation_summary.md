# F6_FADE_V1 — VALIDATION Summary

**Classification: VALIDATION_PASS**

Ran exactly once, per `results/task68_f6_freeze/validation_protocol.json`'s
pre-registered pass_logic (declared before any validation outcome was known,
back in Task 68A). No threshold was invented or adjusted after seeing these
numbers.

Period: **2024-02-01 → 2024-03-15** (locked in
`holdout_selection_lock.json` before any F6 outcome was computed against
this data — see `historical_exposure_audit.md` for why 2024 is defensible).
Universe: canonical 35-symbol universe, no substitutions. Dataset hash
`30a64179e8e4`. Strategy fingerprint `6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084` — reconfirmed to match before this run.

## Headline numbers

| Metric | Value |
|---|---|
| Candidates evaluated | 1,217 |
| Trades | 43 |
| Long / Short | 33 / 10 |
| Symbols with a trade | 20 |
| Trading days with a trade | 10 |
| Gross expectancy | +0.438% |
| Net expectancy @10bps | **+0.338%** |
| Profit factor @10bps | 2.05 |
| Win rate | 67.4% |
| Median trade (net) | +0.585% |
| Max drawdown (cum. net_return) | −3.45 pts |

## Cost sensitivity

| Cost | Expectancy | Total return | Profit factor |
|---|---|---|---|
| 0bps | +0.438% | +18.84% | 2.49 |
| 5bps | +0.388% | +16.69% | 2.26 |
| 10bps | +0.338% | +14.54% | 2.05 |

Degradation from 0→10bps is modest (~23% relative) — the edge is not an
artifact of an unrealistically low cost assumption.

## Bootstrap (95% CI, clustered by symbol — Task68A's pre-registered primary method)

point_estimate=+0.338%, **ci_low=−0.071%**, ci_high=+0.694%, n_groups=20.
CI does not fully exclude zero (not required to), and ci_low is close to
but does not breach the pre-registered floor of −0.10% (−1× the 10bps cost
assumption). Secondary session/date-clustered CI (n_groups=10):
ci_low=−0.136%, ci_high=+0.653% — also inside the floor, slightly wider as
expected with fewer clusters.

## Concentration

top1_symbol=22.4%, top1_day=29.6% (both ≤ the 40% disqualifying threshold).
top3_symbol=46.1%, top3_day=65.9% — informational only (not a pass/fail
criterion), but worth noting: with only 20 symbols and 10 days contributing,
some concentration is expected at this small sample size.

## Outlier sensitivity

Removing the best 3 trades still leaves expectancy at **+0.193%** — positive,
comfortably above the −0.338% floor (criterion 4: must stay > −1× the
primary net expectancy). The edge is not manufactured by a handful of
outsized winners.

## Long vs. short

Long expectancy +0.460% (33 trades) vs. short expectancy −0.063% (10
trades). The spec explicitly flagged this asymmetry as unconfirmed at
freeze time and instructed a signed breakdown be reported here — done. Per
the frozen spec, this is **informational, not a pass/fail requirement**
(the pooled/symmetric gross_expectancy is what criterion 2 checks, and it
is positive). Short-side sample (10 trades) is too small to draw an
independent conclusion either way.

## Integrity diagnostics

- Decision→entry delay: exactly 60 seconds for every trade (1-minute bar,
  matches the frozen "next bar after decision" rule exactly).
- Holding duration: exactly 3,600 seconds (60 minutes) for every trade —
  100% `FIXED_60M_EXIT`, zero `SESSION_CLOSE_EXIT` in this window.
- Causal violations (decision at/after entry): **0**.
- Rejection breakdown: `DATA_NOT_READY`=791, `OPENING_MOVE_BELOW_THRESHOLD`=383
  — zero `NO_NEXT_BAR_FOR_ENTRY`/`NO_VALID_EXIT`/`DUPLICATE_SIGNAL`, a fully
  clean funnel with no unexplained rejection category.
- Data quality: 35/35 FULL, zero duplicate/out-of-order/NaN/Inf/invalid-OHLC/
  negative-volume/future-timestamp rows (see `validation_data_quality.json`).

## Pass criteria (all 8, per validation_protocol.json, unmodified)

| # | Criterion | Result |
|---|---|---|
| 1 | net_expectancy_10bps > 0 | **PASS** (+0.338%) |
| 2 | gross direction consistent with discovery | **PASS** (+0.438%) |
| 3 | top1 symbol/day ≤ 40% | **PASS** (22.4% / 29.6%) |
| 4 | top-3-winners-removed > −1× net expectancy | **PASS** (+0.193% > −0.338%) |
| 5 | trades≥30, symbols≥10, days≥10 | **PASS** (43 / 20 / 10) |
| 6 | bootstrap ci_low not grossly negative (> −0.10%) | **PASS** (−0.071%) |
| 7 | realistic costs don't erase edge | **PASS** |
| 8 | no causal/integrity violation | **PASS** |

**All 8 criteria pass.** This is a real pass, but a narrow one on two
dimensions worth being honest about: `session_coverage` sits exactly at the
minimum floor (10, not comfortably above it), and the bootstrap CI's lower
bound, while inside the pre-registered floor, is close to zero. This is not
an overwhelming result — it is a defensible one under the frozen,
pre-registered bar. Per the protocol, replication now proceeds exactly once
against the separately locked REPLICATION window, unmodified.
