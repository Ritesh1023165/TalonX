# TASK 95B — Family D — Oversold Rebound (Multi-Day Mean Reversion)

**Hypothesis:** a multi-day drawdown / daily-oversold condition is followed by a long-only rebound
over 3–5 days.

**Pre-registered bins:** 5-day prior return in the discovery bottom quintile; daily RSI(14) ≤ 30;
in > 15 % drawdown from the all-time high **and** a fresh bottom-decile 3-day drop; in > 20 %
drawdown **and** daily RSI ≤ 35. Primary horizon 3–5 d. Metric = net excess bps over the matched
unconditional-long comparator; the two drawdown bins are also re-scored against a **drawdown-matched
comparator** (unconditional long over all "> 15 % drawdown" bars). CIs: symbol-block bootstrap +
non-overlapping subsample.

## Result — 11 experiments, 0 pass (this is the family that came closest)

| Bin | n | excess net @5 bps (vs global) | @10 bps | @20 bps | non-overlap CI | block-boot CI | best-year share | why it fails |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 5-day prior return bottom quintile (k=3) | 6,041 | +6.0 | −4.0 | — | [−0.8, +89] | [+6.6, +55] | — | S2 (< +25), S3, S4 |
| daily RSI(14) ≤ 30 (k=5) | 891 | +1.7 | −8.3 | — | [−96, +?] | [−57, +?] | — | S2, S3, S4, S6 |
| **> 15 % drawdown + fresh bottom-decile 3-day drop (k=3)** | 2,151 | **+25.2** | +15.2 | −4.8 | [+1.7, +89] | [+15, +55] | **0.52 (2020)** | **S7** — best-year 52 % is 2020 crash-recovery; vs the drawdown-matched comparator net @5 drops to **+17.3** (< S2); 2022 excess **−14 bps** |
| **> 20 % drawdown + daily RSI ≤ 35 (k=5)** | 1,574 | **+35.3** | +25.3 | +5.3 | **[−91, +86]** | [−1.1, +97] | **0.64** | **S4** (non-overlap CI spans zero) + **S7** (best-year 64 %) |

### Drawdown-matched comparator (does the *fresh drop* add value beyond just being in a drawdown?)

`D-deepdd_fresh3ddrop` vs the "> 15 % drawdown" unconditional mean (22.0 / 34.3 / 56.4 bps at
2 / 3 / 5 d):

| k | gross excess | net @5 bps | net @10 bps | non-overlap CI low | by-year excess (bps) |
|---:|---:|---:|---:|---:|---|
| 2 | −2.2 | −12.2 | −22.2 | −35.4 | 2020 −31 · 2021 +53 · 2022 −14 · 2023 +117 |
| 3 | +27.3 | +17.3 | +7.3 | −6.1 | 2020 +117 · 2021 +60 · **2022 −22** · 2023 +98 |
| 5 | +51.7 | +41.7 | +31.7 | −78.6 | 2020 +176 · 2021 +116 · **2022 −12** · 2023 +90 |

## Interpretation

The oversold family is the only one with a **positive-signed** effect that approaches the economic
bar: buying a sharp fresh drop while already deeply drawn-down returns +25–35 bps net @5 bps over
3–5 days in discovery. But it fails on **concentration and instability**, not magnitude:

- **It is a crash-recovery / V-bottom phenomenon.** Positive excess is +100 to +200 bps in 2020
  (COVID bottom) and 2023 (bear-market bottom), and **negative in 2022** — the year with the most
  events. The signal "buys the dip"; in discovery that dip was usually a V-bottom because 2020 and
  2023 were recovery years. In a grinding bear (2022) the same signal loses.
- Removing the best year takes the drawdown-matched 3-day excess to ≈ 0; the non-overlap CI includes
  zero at every horizon against the matched comparator (S4).
- Against a **drawdown-matched** comparator (isolating the "fresh drop" from "being in a drawdown"),
  the 3-day excess is only +17.3 bps — below the +25 bar.
- `D-dd20_rsi35` looks better in raw terms (+35 net @5, survives 20 bps) but its non-overlap CI is
  [−91, +86] — statistically indistinguishable from zero once overlap is corrected.

No oversold-rebound candidate advances. The family's signal is real but **regime-episodic** (V-bottoms
only) and does not generalise across the four discovery regimes.
