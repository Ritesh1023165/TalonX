# TASK 95B — Phase 14 — Turnover / Capacity / Exposure

Operational-plausibility check only — no portfolio construction, no sizing. Discovery window:
880 trading days ≈ 176 weeks, 35 symbols.

| Bin | events (discovery) | events / symbol / week | avg hold (days) | implied concurrent positions / symbol | plausible? |
|---|---:|---:|---:|---:|---|
| `E-gapdn_p10 × vol_high` (k=3) | 1,177 | 0.19 | 3 | ~0.6 | yes — ~1 entry per symbol every 5 weeks |
| `D-deepdd_fresh3ddrop` (k=3) | 2,151 | 0.35 | 3 | ~1.1 | yes |
| `D-dd20_rsi35` (k=5) | 1,574 | 0.26 | 5 | ~1.3 | yes |
| `D-5d_drawdown_q1` (k=3) | 6,041 | 0.98 | 3 | ~2.9 | borderline — ~1 entry/symbol/week, up to ~3 stacked |
| `A-mom_60d_q1` (k=3) | 5,658 | 0.92 | 3 | ~2.8 | borderline |
| `E-gapdn_p10` unconditioned (k=3) | 3,039 | 0.50 | 3 | ~1.5 | yes |
| `C-new_hi20` (k=3) | 2,590 | 0.42 | 3 | ~1.3 | yes |

## Reading

**Turnover is not the reason anything failed.** The oversold/gap bins that had positive raw excess
(`E-gapdn_p10 × vol_high`, `D-deepdd_fresh3ddrop`, `D-dd20_rsi35`) run at **0.19–0.35
events/symbol/week** with ~1 concurrent position per symbol — comfortably inside the S8 gate
(≤ 2 events/symbol/week) and operationally trivial to run as a swing book. A strategy built on any
of them would trade rarely and hold briefly.

The **exposure caveat** that *would* matter if any candidate had survived: the events cluster in
time (market-stress episodes). `E-gapdn_p10 × vol_high` fires ~590 times in 2022 and ~420 in 2020 Q1–Q2
but only tens of times per year otherwise — so realised exposure would be lumpy: near-zero in calm
years, then many simultaneous entries across correlated names during a sell-off. That concentration
of *timing* is the same weakness Phase 13 flags as a P&L problem; here it also means the phenomenon
could not be relied on to produce steady opportunity flow (owner intent: `REGULAR_OPPORTUNITY`).

No candidate advances, so no capacity/exposure modelling is warranted.
