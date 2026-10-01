# TASK 93 — Phase 11: Statistical Confidence

## The sample

| Partition | Bars | Symbols | **Trades** |
|---|---:|---:|---:|
| Segment A (2025-01-24 → 2025-08-14) | 2,565,682 | 35 | **1** |
| Segment B (Task 74S, 2025-08-15 → 2026-08-14) | 1,903,044 | 10 | **0** |
| **All available history combined (~18.7 months)** | **4,468,726** | 35 (union) | **1** |

## What can and cannot be estimated

**n = 1.** No confidence interval, bootstrap, t-test, Sharpe, Sortino, or profit-factor uncertainty is
meaningful. The engine itself emits a `SMALL SAMPLE (1 trade)` warning and declines to compute
`expectancy_ci` / `average_r_ci` (`baseline_summary.json` → `metrics.*.expectancy_ci: null`). The
normal-approximation / CLT machinery these methods rely on needs roughly **30+** independent
observations; the repository's own prior protocols (Task 54/56/59, and `TASK94_RESEARCH_PROTOCOL.md`
criterion C1) use **≥ 30 trades** as the floor for even attempting an edge claim.

| Quantity | Point value (Segment A) | Uncertainty |
|---|---|---|
| Win rate | 1/1 = 100% | 95% interval is the whole `[0, 1]` — uninformative |
| Expectancy | +5.99 R | undefined at n=1 (no dispersion estimate) |
| Profit factor | ∞ (0 losing trades) | undefined |
| Total R | +5.99 R | it *is* the single observation |
| Max drawdown | 0 R | trivial (one winning trade) |

## Framing the one observation against noise

Phase 12's random-eligible-long comparator (349-min hold, 0 bps, n ≈ 16,000) has **mean +4 bps, median
+0.5 bps, hit-rate 50.2%, std ≈ 203 bps**. The single TalonX trade returned **+245 bps raw** (+5.99 R
on a $0.262/share stop). That is ≈ **1.2 standard deviations** above the random-entry mean — an
outcome that occurs by chance in roughly **1 in 9** random single entries. **It is fully inside the
noise band of a single lucky draw.** It provides essentially no evidence for a repeatable edge.

## Prior populations (context, not this strategy)

Even the *larger* prior trade populations — all against **more permissive, now-superseded** strategy
versions — were underpowered and cost-fragile:

| Task | n | 0-bps expectancy 95% CI | 5-bps result |
|---|---:|---|---|
| 26 | 26 | [−0.63 R, +0.96 R] (spans 0) | −4.6 R total, PF 0.81 |
| 36 | 7 | [−1.03 R, +0.75 R] (spans 0) | PF ≤ 0.55 |
| 54 | 89 | [−0.19 R, +0.71 R] (spans 0) | −0.29 R/trade |
| 56 (holdout) | 105 | — | RSI −0.24 R, MACD −0.43 R/trade |

Every one of these confidence intervals includes economically weak-or-negative outcomes, and each was
computed on a strategy that is **not** the current frozen one.

## Conclusion

There is **no statistical basis** to characterise the current frozen strategy's edge in either
direction. The evidence is not "weak" in the sense of a small positive point estimate with a wide CI —
it is **absent**: there is no trade population. The correct statement is *the strategy does not trade
often enough to be evaluated*, and the one trade that exists is indistinguishable from a single lucky
random entry. Any confidence claim (positive or negative) at this sample size would be a
misrepresentation.
