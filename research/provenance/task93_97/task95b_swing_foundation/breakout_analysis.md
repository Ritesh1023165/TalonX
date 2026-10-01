# TASK 95B — Family C — Breakout / Range Expansion

**Hypothesis:** a new 20-day high, a strong close in the range, or an ATR-scale up day is followed by
positive multi-day continuation.

**Pre-registered bins:** `adj_close(t) ≥ prior 20-day high`; same + volume ≥ 1.5× 20-day median;
close in the top decile of the prior 20-day range (`range_pos_20 ≥ 0.9`); up day ≥ 2× daily ATR%.
Primary horizon 2–3 d. Metric = net excess bps over the matched unconditional-long comparator, plus
comparison to matched random events (Phase 15 framework).

## Result — 11 experiments, 0 pass

| Bin | n | excess net @5 bps | @10 bps | non-overlap CI low | block-boot CI low | years+ | symbols+ | why it fails |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| new 20-day high (k=3) | 2,590 | **−24.0** | −34.0 | −48.2 | −37.0 | 0.25 | 0.26 | breakouts **underperform** the drift |
| new 20-day high + volume ≥ 1.5× (k=3) | 722 | **−24.5** | −34.5 | −77.3 | −56.0 | 0.50 | 0.31 | volume confirmation does not help |
| close in top decile of 20-day range (k=3) | 4,812 | **−19.0** | −29.0 | −18.5 | −27.8 | 0.25 | 0.29 | strong closes fade |
| up day ≥ 2× ATR% (k=2) | 260 | **−31.1** | −41.1 | −122.6 | −64.6 | 0.75 | 0.37 | S1 (n < 300) + large negative |

## Interpretation

**Breakouts are negatively predictive here.** Every breakout / strong-close / range-expansion bin
underperforms the unconditional long drift by 19–31 bps over the next 2–3 days. In this 35-name
mega-cap universe over 2020–2023, a fresh 20-day high or a top-decile close is followed by
**mean-reversion, not follow-through** — buying strength at these horizons is a losing filter even
before cost. Volume confirmation does not rescue it. No breakout candidate advances; the family is a
clean negative result.
