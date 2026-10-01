# TASK 95G — Family A — Relative Momentum Replication (broad S&P 500)

**Exact replication of Task 95E Family A** on the historically-correct ~500-name point-in-time
S&P 500. `rel_n` = own trailing n-day return − equal-weight member-universe trailing n-day return
(market drift removed by construction). Top **decile** (~50 names), daily rebalance, 819 discovery
ranking dates, `top_decile_excess` over the equal-weight eligible-member universe.

## Result — relative strength is a **NEGATIVE** predictor on the honest universe

| lookback | k3 `top_decile_excess` / net@5 | k5 / net@5 | k10 / net@5 | symbol-block CI (k3) | years positive | verdict |
|---|---:|---:|---:|---|---:|---|
| rel 1d | −16.1 / −41.8 | −23.9 / −66.9 | −34.4 / −120.4 | **[−21.1, −11.3]** | 0/4 | FAIL |
| **rel 3d** | **−26.3** / −42.1 | −36.3 / −62.7 | −36.9 / −89.7 | **[−32.6, −20.5]** | 0/4 | FAIL |
| rel 5d | −25.6 / −38.0 | −34.6 / −60.0 | −37.9 / −85 | [−32, −19] | 0/4 | FAIL |
| rel 10d | −18.8 / −27.7 | −18.4 / −33.2 | −20.7 / −50.2 | **[−25.3, −12.7]** | 1/4 | FAIL |
| rel 20d | −17.9 / −24.3 | −26.0 / −36.6 | −30.8 / −52.1 | [−24.6, −11.1] | 0/4 | FAIL |
| rel 60d | −20.5 / −24.4 | −29 / −38 | −31 / −52 | [−27, −14] | 0/4 | FAIL |

(bps of `top_decile_excess`; before / after turnover-adjusted 5-bps cost. Full numbers `EXPERIMENT_LEDGER.csv`.)

## Decile gradient — a clean short-term **reversal**

`rel_3d`, forward 3-day excess by decile (D1 = strongest recent relative strength → D10 = weakest):

| D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **−26.3** | −19.1 | −15.4 | −10.5 | −13.6 | +3.8 | +7.0 | +13.9 | **+34.4** | +26.7 |

Near-monotone: the top-decile recent winners **underperform** the index over the next 3 days, the
bottom-decile losers **outperform**. `top_minus_bottom` = **−53 bps**. Same shape for every lookback
1d–20d and for Family C (vol-adjusted). This is the textbook cross-sectional short-term reversal, and
it is **statistically strong** — the symbol-block CI on D1 excess is entirely negative for every
lookback, and the date-block CI is negative for the short lookbacks.

## This INVERTS the Task 95E near-miss

| | Task 95E (35 survivor names, top 20% = 7 names) | Task 95G (500 point-in-time names, top 10% ≈ 50 names) |
|---|---:|---:|
| `rel_10d` top excess, k5 | **+27.9 bps** ("DISCOVERY_PASS" pre-adjudication) | **−18.4 bps** |
| years positive | 4/4 | 1/4 (2023 only, +1.3) |
| symbol-block CI | not run (would have killed it — see 95E adjudication) | **[−25.3, −12.7]** — entirely negative |
| decile gradient | non-monotone, D1 spike only | monotone reversal, D1 worst |

Task 95E's `rel_10d` "signal" **does not replicate** — it inverts to a significantly negative effect.
It was a concentration + survivorship artifact of 7 mega-caps (TSLA/NVDA/AMD) in two strong-
dispersion years.

## Robustness diagnostics

- **Not concentrated:** best single symbol ≤ 1.5% of positive top-decile excess-R, top-3 ≤ 4.3%
  (vs Task 95E's TSLA at 12–25%). The negative is broad.
- **By year:** negative in every discovery year for most lookbacks (2020 worst, −42 to −69).
- **Current vs removed members:** the reversal is **stronger among later-removed constituents**
  (rel_3d: current −20.7, removed −49.1) — the opposite of a survivorship rescue; the survivor-only
  35-name set was *masking* the true negative.
- **Non-overlapping 5-day rebalance:** still negative (−10 to −21 bps).

## Verdict

**Family A — all 6 `DISCOVERY_FAIL`.** On a historically-correct broad universe, cross-sectional
relative momentum at 1–10 days is a **negative-excess (reversal)** signal, not a source of long-only
alpha. Breadth did not rescue Task 95E's momentum near-miss — it exposed it as an artifact.
