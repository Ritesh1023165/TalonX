# TASK 93 — Phase 10: Parameter Stability Without Optimisation

**No tuning. No parameter selected. No production value proposed.** The only question here: is the
Segment-A result (**1 trade, +5.99 R at 0 bps**) *structurally* stable or *knife-edge* — i.e. would a
small perturbation of an existing frozen parameter change it materially? Because the result is n=1, the
honest answer is dominated by that: **any** perturbation that adds or removes that one trade swings the
entire "performance" from +5.99 R to 0 or to something else — so at n=1 the *performance* result is
maximally knife-edge by construction. What is more informative is the **funnel-count** sensitivity,
which shows the binding constraints do *not* move sharply.

## Volatility floor `min_atr_pct` (currently 0.25% on 1-min ATR)

From the per-bar volatility telemetry (2,561,517 evaluations; `parameter_stability_volatility_grid.csv`),
**no re-run** — the gate is a pure threshold on a value already recorded:

| Threshold | Bars passing | % of all evals | × vs 0.25% |
|---:|---:|---:|---:|
| 0.05% | 2,122,824 | 82.9% | 11.5× |
| 0.10% | 1,071,478 | 41.8% | 5.8× |
| 0.15% | 560,531 | 21.9% | 3.0× |
| 0.20% | 312,174 | 12.2% | 1.7× |
| 0.22% | 252,046 | 9.8% | 1.4× |
| **0.25% (current)** | **184,842** | **7.2%** | **1.0×** |
| 0.28% | 136,927 | 5.3% | 0.74× |
| 0.30% | 113,742 | 4.4% | 0.62× |
| 0.35% | 73,827 | 2.9% | 0.40× |
| 0.40% | 49,827 | 1.9% | 0.27× |

`atr_pct` percentiles over all evaluated bars: p50 0.087%, p75 0.139%, **p90 0.219%**, p95 0.287%, p99
0.49%. The 0.25% floor sits **between the 90th and 95th percentile of every bar** (confirms Task 38).

**Stability read:** the *pass-rate* response is **smooth, not knife-edge** — pass-rate roughly doubles
per ~0.05% loosening; there is no cliff at 0.25%. But it is *structurally high*: even halving the floor
to 0.125% still admits only ~1/3 of bars, and (Phase 7 counterfactual) the newly-admitted bars have
~zero forward long edge, while the *confluence* gate remains the next wall regardless. So loosening
`min_atr_pct` alone moves candidate volume a lot and executable-trade volume ~not at all — the result's
**sparsity is stable** to this parameter; only its (n=1) *P&L* is not.

## Confluence floor `confluence_score_min` (currently 2)

From the candidate telemetry: `confluence_score` distribution over 7,647 candidates — **0 → 6,554
(85.7%), 1 → 1,058 (13.8%), 2 → 35 (0.46%)**. Nothing scored above 2 in the whole Segment A.

- Lowering to **1**: admits 1,058 + 35 = 1,093 candidates (14.3× the current 35). Phase 7's
  counterfactual on the sub-threshold bullish regular population shows **weak forward returns** (+9 bps
  at 15 min, 52% hit) vs the confluence≥2 survivors (+114 bps, 80%) — i.e. score-1 candidates look
  much closer to noise than to the score-2 set. Loosening here would add mostly weak candidates.
- Raising to **3**: admits **0** candidates in Segment A → 0 trades.

**Stability read:** the confluence floor is at a genuine **breakpoint** — score 2 is the *only* level
with any candidates that show forward edge, score 3 kills the funnel entirely, score 1 dilutes toward
noise. This parameter is closer to knife-edge than the volatility floor, but in the direction of
"there is barely anything at score 2 and nothing above it", not "a small change flips a healthy result."

## R:R gate (currently ≥ 1.5) and HTF trend gate

The last 15 → 2 → 1 narrowing (Phase 7 funnel) is where HTF `trend_component` and `risk_reward_ratio ≥
1.5` remove 14 of the final 15 regular-session bullish confluence candidates. At n=15 → 1, perturbing
either gate is untestable for *performance* — removing the R:R gate would have admitted 1 more of the
15 (the INTC 2025-02-14 candidate, RR 0.63), removing the trend gate would have admitted ~13 more
(mostly `trend_component=False`). Whether that is correct filtering is a **Task 94** question (area A2
/ A4), not answerable from this sample.

## Conclusion

- **Sparsity of the result is structurally stable** — no nearby setting of the volatility or confluence
  floor turns 1 trade / 6.7 months into anything resembling `REGULAR_OPPORTUNITY`, because the two
  gates compound and the second one (confluence) has almost nothing at its passing level and nothing
  above it.
- **The +5.99 R P&L figure is maximally fragile** — it is one trade; any perturbation that touches it
  changes everything. This is a restatement of "n=1", not an independent finding.
- **No parameter is selected or recommended.** These are fragility diagnostics only. The evidence that
  the *volatility-regime instrument itself* (not its threshold) is the wrong tool is Task 38's +
  Phase 7's, and it is a **Task 94 area (A1)**, not a Task 93 change.
