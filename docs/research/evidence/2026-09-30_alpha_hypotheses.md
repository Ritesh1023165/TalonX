# Alternative causal entry hypotheses — PAPER_SIGNAL population, 2026-09-28 + 2026-09-29 (exploratory)

Research only: offline counterfactuals, no live change, no Telegram, no orders.
- **Unchanged:** CONTROL policy, SQF_V1 and DTU.
- **Tool:** `talonx_paperperf/alpha_hypotheses.py`.
- **Data:** `2026-09-30_alpha_research/alpha_2026-09-28_2026-09-29.json`.
- **Sep 30:** no Sep 30 Signal existed when this analysis ran (10:20Z). Sep 30 is an **unseen holdout**, to be
  re-run descriptively after its EOD forensic.

## Method

- **Population:** 307 CONTROL Signals, 301 with an actionable entry. T0 is the first 1-minute SIP bar at or after the
  Telegram SENT time.
- **Causality:**
  - Every rule decides only from bars that have **completed**, and enters at the next bar's open. Breakouts fill at the
    buy-stop level, or at the bar's open if it gapped above.
  - H3's volume baseline is the 30 minutes *before* T0.
  - No future high, low, volume or outcome is used to choose an entry.
- **Exits:** fixed at +15, +30 and +60 minutes and the close, measured from the *actual* simulated entry. +30 minutes
  is the primary exit.
- **Cost and portfolio:** identical to the forensic. Cost is max(V2 20 bps, measured spread at T0). The portfolio is
  $100k, $10k per position, up to 10 concurrent.
- **Consistency check:** H0 reproduces the forensic exactly (n = 301, gross −0.055%, net −0.573%, −$11,279).

## Results (+30 minutes from each hypothesis's own entry)

| Hypothesis | Trades / 301 | Gross | Net | Win | PF | P&L | Max DD | Top-3 pp | Mean without best 3 | Entry delay |
|---|---|---|---|---|---|---|---|---|---|---|
| **H0 CONTROL** (immediate long) | 301 | −0.055% | −0.573% | 30.3% | 0.28 | −$11,279 | −$11,501 | 17.0 | −0.64% | 0 min |
| H1 pullback 0.5% + prior-high | 267 | −0.153% | −0.693% | 25.2% | 0.21 | −$14,396 | −$14,425 | 9.9 | −0.74% | 14 |
| H1 pullback 0.5% + reclaim | 138 | −0.222% | −0.827% | 24.6% | 0.19 | −$10,083 | −$10,542 | 9.5 | −0.92% | 19 |
| H1 pullback 1.0% + prior-high | 181 | −0.123% | −0.783% | 29.7% | 0.22 | −$11,434 | −$11,659 | 9.9 | −0.86% | 25 |
| H1 pullback 1.0% + reclaim | 59 | −0.050% | −0.992% | 23.6% | 0.24 | −$5,456 | −$5,994 | 9.9 | −1.24% | 29 |
| H1 pullback 1.5% + prior-high | 103 | −0.176% | −0.963% | 29.0% | 0.22 | −$8,958 | −$9,355 | 10.0 | −1.11% | 27 |
| H1 pullback 1.5% + reclaim | 25 | +0.166% | −1.349% | 27.3% | 0.26 | −$2,969 | −$3,126 | 8.3 | −2.00% | 21 |
| H1 pullback 2.0% + prior-high | 68 | −0.232% | −1.174% | 23.9% | 0.19 | −$7,864 | −$8,299 | 9.5 | −1.38% | 22 |
| H1 pullback 2.0% + reclaim | 17 | +0.133% | −1.610% | 18.8% | 0.24 | −$2,576 | −$2,733 | 8.3 | −2.62% | 18 |
| H2 breakout of T0-bar high | 251 | −0.099% | −0.598% | 27.4% | 0.25 | −$11,956 | −$12,315 | 11.8 | −0.66% | 3 |
| H2 breakout of first-5-min high | 208 | −0.066% | −0.549% | 26.7% | 0.26 | −$8,492 | −$9,294 | 10.4 | −0.61% | 10 |
| H3 post-signal RVOL ≥ 1.5 | 44 | −0.198% | −0.668% | 21.6% | 0.20 | −$2,473 | −$2,706 | 3.6 | −0.83% | 5 |
| H3 RVOL ≥ 2.0 | 26 | −0.120% | −0.625% | 27.3% | 0.26 | −$1,374 | −$1,470 | 3.6 | −0.91% | 5 |
| H3 RVOL ≥ 3.0 | 6 | +0.075% | −0.176% | 20.0% | 0.51 | −$88 | −$118 | 0.4 | −0.62% | 9 |
| H4 reversion reference (counterfactual short at T0) | 301 | +0.055% | −0.464% | 32.5% | 0.38 | −$8,258 | −$8,320 | 18.4 | −0.54% | 0 |

**Positive gross appears only with n ≤ 25** (H1 1.5/2.0% reclaim, H3 RVOL ≥ 3), which is noise at this sample size.

**Power check, +30m gross, 95% CI:**

| Rule | 95% CI (gross) | Median cost |
|---|---|---|
| H0 | [−0.23%, +0.12%] | 0.26% |
| H2 first-5-min breakout | [−0.29%, +0.16%] | 0.26% |
| H1 1.0% | [−0.37%, +0.12%] | 0.31% |

For these rules, a gross edge large enough to cover costs is **excluded at about 95%**.

**Other horizons, gross:**

| Rule | +15m | +30m | +60m | Close |
|---|---|---|---|---|
| H0 | −0.07% | −0.06% | −0.13% | +0.13% |
| H4 | +0.07% | +0.06% | +0.13% | −0.13% |

Nothing clears cost at any horizon.

## Path analysis (H0, first 60 minutes)

- **Order of extremes:** the MFE came first in 157 cases, the MAE first in 140, and 4 on the same bar. That's a coin
  flip.
- **Timing:** the median time to MFE is 18 minutes, and to MAE 21 minutes.
- **Size:** median MFE +1.07% vs MAE −1.12%, so the swings are real but carry no direction.
- **Pullbacks:** 93% pull back ≥0.5%, 66% ≥1.0%, 38% ≥1.5% and 25% ≥2.0%, with a median maximum pullback of 1.28%.
- **Resumption:** after a pullback, only **54% / 34% / 24% / 24%** resume above the prior high. The deeper the
  pullback, the less likely a resumption, so waiting for a dip mostly selects failing moves. That's why H1 is
  worse than H0.

## Conditionings of H0 (explanatory only; not filters)

Gross +30m per bucket; n shown.

**H5 time of day:**

| Window | n | Gross | Net | Win |
|---|---|---|---|---|
| Opening hour | 44 | −0.17% | −0.66% | 23% |
| Late morning | 77 | −0.23% | −0.86% | 22% |
| Midday | 88 | +0.09% | −0.41% | 39% |
| Late session | 92 | +0.04% | −0.40% | 34% |

The opening hour and late morning are the weakest windows. No window clears cost.

**H6 catalyst:**

| Catalyst | n | Gross | Wins |
|---|---|---|---|
| **8-K only** | 10 | **−1.25%** | 0 |
| Form 4 / insider | 19 | −0.32% | 1 |
| None | 247 | −0.00% | — |
| Other SEC | 17 | +0.06% | — |
| 6-K | 8 | +0.31% | — |

Catalysts do not add continuation. 8-K-only is consistently the worst.

**DTU state:** gross is essentially equal; the net gap is cost.

| State | n | Gross | Net |
|---|---|---|---|
| Core | 71 | −0.04% | −0.28% |
| Event-promoted | 225 | −0.05% | −0.67% |

- **Event-promoted names do not carry different alpha.** They carry wider spreads.

**Move size** (H0 gross vs reversion gross):

| Move | n | H0 gross | Reversion gross | MFE / MAE |
|---|---|---|---|---|
| 3–5% | 244 | −0.02% | — | — |
| 5–10% | 42 | −0.17% | — | ±3% |
| 10–20% | 15 | −0.34% | **+0.34%** (median +1.36%, 57% win) | +7.9% / −4.8% |

- Bigger moves swing more.
- The 10–20% reversion hint rests on **15 trades**.

**Liquidity and price:**

| Bucket | n | Gross |
|---|---|---|
| ADV $20–100M | 104 | +0.11% (best liquid bucket; net −0.20%) |
| ADV <$5M | 69 | −0.13% |
| Price <$3 | 25 | −0.62% |
| Price $3–5 | 32 | −0.42% |
| Spread >100 bps | 28 | +0.24% gross, −2.17% net |

For wide-spread names, cost alone destroys any movement.

## Interpretation

- **`CONTINUATION_PREMISE_FAILURE_SUPPORTED`.**
  - Every continuation entry rule tested (immediate, pullback plus confirmation, breakout, volume confirmation) has
    gross ≤ 0 at an adequate sample.
  - The confidence intervals exclude a gross edge that could cover costs.
  - Better entry timing does not help: pullbacks select failing moves, and breakouts are the same as H0.
- **Reversion is not materially better overall.** It is the mirror image of a directionless population (+0.055%
  gross, still negative net), so `REVERSION_HYPOTHESIS_WARRANTS_FORWARD_TEST` is **not** raised. The only hint is for
  moves of 10% or more, on n = 15, which is too small to register.
- **Timing and conditioning hints:** midday/late-session and liquid ($20–100M ADV) continuation have slightly positive
  gross, up to +0.11% (see the tables above). These are conditionings of the same failed premise, and under the
  failure rule they are not promoted into more filters.
- **TOP_2_FORWARD_HYPOTHESES: NONE** qualify: none has positive gross, an adequate sample and low concentration
  together. **PRE_REGISTER_NEXT: NO.**
- **The Sep 30 holdout** is re-run descriptively for every hypothesis after tonight's EOD, to check that the null
  result holds.

## What this says about the next hypothesis

The PAPER_SIGNAL population is a set of stocks already moving ~1% in either direction at the moment of delivery.
Timing the entry within that move cannot create direction that isn't there. A materially different hypothesis needs
**new information** available *before* or *independent of* the price move itself, rather than another entry trigger
on the same move. Examples: pre-move event surprise, cross-sectional or relative strength versus the sector or
market, or order-flow imbalance. That is a new research task, not a filter.
