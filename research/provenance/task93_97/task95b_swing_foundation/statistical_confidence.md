# TASK 95B — Phase 12 — Statistical Confidence & Overlapping-Horizon Correction

## The overlap problem

k-day forward returns computed on consecutive daily bars share `k−1` of their `k` days. A discovery
population of, e.g., 6,000 events at a 3-day horizon contains only ~2,000 non-overlapping windows per
symbol-block. Treating the 6,000 as i.i.d. understates the standard error by roughly `√k` and
manufactures significance. **No confidence claim in Task 95B uses a naïve i.i.d. bootstrap over
overlapping returns.**

## Methods applied to every reported effect

1. **Non-overlapping subsample.** Within each symbol, keep every k-th event (disjoint `[t, t+k]`
   windows). Report `n_nonoverlap`, its mean excess, and a Gaussian 95 % interval from that
   subsample's own SE. This is the most conservative check — it discards ~`(k−1)/k` of the data.
2. **Symbol-block bootstrap.** Resample the 35 symbols with replacement (35 blocks), concatenate
   each drawn symbol's full event series, recompute the mean excess; 3,000 iterations; report the
   2.5 / 97.5 percentiles. This preserves within-symbol serial dependence and captures
   cross-symbol correlation (all 35 are correlated mega-cap tech, so a few symbols' good runs can
   carry a naïve mean).
3. **Pass rule (protocol S4):** the excess-net-bps 95 % lower bound must be **> 0 under *both*** the
   non-overlapping mean and the symbol-block bootstrap, evaluated against the **correct comparator**
   (regime-matched where the candidate is regime-conditional).

## Results

| Effect | non-overlap CI (bps) | block-boot CI (bps) | comparator | S4 |
|---|---|---|---|---|
| `E-gapdn_p10 × vol_high` (k=3) vs **global** | [+6.4, +138.6] | [+44.7, +112.0] | global (wrong) | passes vs wrong comparator |
| `E-gapdn_p10 × vol_high` (k=3) vs **vol_high baseline** | **[−22.3, +109.9]** | [+15.4, +83.0] | regime-matched | **FAIL** (non-overlap spans 0) |
| `E-gapdn_p10 × vol_high` (k=5) vs vol_high baseline | **[−208, −8.6]** | [+7.0, +124.1] | regime-matched | **FAIL** (non-overlap fully negative) |
| `D-deepdd_fresh3ddrop` (k=3) vs global | [+1.7, +89.3] | [+15.2, +55.5] | global | marginal; **FAIL** vs DD15-matched: [−6.1, +81.5] |
| `D-dd20_rsi35` (k=5) vs global | **[−91.2, +86.3]** | [−1.1, +97.0] | global | **FAIL** (both span 0) |
| `A-mom_60d_q1` (k=3) vs global | [+6.5, ...] | [+7.9, ...] | global | passes CI but **S2** (magnitude +20.8 < +25) |
| every momentum/breakout bin | negative or spans 0 | negative or spans 0 | global | FAIL |

## Multiple testing

68 experiments (5 families × coarse pre-registered bins × 4 horizons for the base bins, + 35
family-best × regime cells). At a nominal 5 % level, ~3–4 "significant" results are expected by
chance. **The economic-magnitude bar (S2: excess-net @5 bps ≥ +25) and the dual-CI rule (S4) are the
real filters, not a p-value.** Because the only cell clearing S2 + S4 against its correct comparator
was zero, no multiple-testing correction is needed to reach the verdict — there is no surviving
positive result to discount. The breadth of the negative (5 families, 68 conditions, 30 k discovery
daily rows across four regimes including a full bear) strengthens it.

## Residual uncertainty

- Discovery is 2020-01 → 2023-06 (four regimes, one bear). An effect that only exists in a regime
  absent from discovery is invisible — but validation (2023 H2 – 2025) and the untouched holdout
  (2025 – 2026) exist for exactly that, and there is no candidate to advance to them.
- The R-normalisation uses a fixed `2.5 × daily ATR%` risk unit (frozen in the protocol before
  results). A different swing stop model would shift R magnitudes but the **bps** metrics — which
  drive the verdict — are stop-free.
