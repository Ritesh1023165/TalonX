# TASK 93 — Phase 7: Full Funnel Decomposition + Counterfactual

Segment A replay (`strategy_version 2ae6216bca70` = current frozen `4b0e5df`, `config_hash 32a7c5b4732e`,
`dataset_hash ad82c9bb459d`, deterministic), 35 symbols, 2025-01-24 → 2025-08-14, 2,565,682 bars.
Machine-readable: `funnel_decomposition.csv`, `counterfactual_forward_returns.csv`,
`_candidate_rejection_breakdown.csv`. Segment B (10 sym, 2025-08-15→2026-08-14) is the Task 74S funnel,
reproduced below by reference (identical strategy).

## 1. The funnel (Segment A)

| Stage | Input | Accepted | Rejected | Acceptance |
|---|---:|---:|---:|---:|
| Post-warmup bar evaluations | 2,561,517 | 2,561,517 | 0 | 100% |
| **Volatility gate** (`ATR(14)/close ≥ 0.25%`, 1-min) | 2,561,517 | **184,842** | 2,376,675 | **7.22%** |
| Candidate generation (trigger fires on a vol-passing bar) | 184,842 | 7,647 | 177,195 | 4.14% |
|  — of which bullish (long-only relevant) | 7,647 | 3,900 | 3,747 bearish | 51.0% |
| **Confluence gate** (`confluence_score ≥ 2`), all directions | 7,647 | **35** | 7,612 | **0.46%** |
|  — confluence ≥ 2 AND bullish | 35 | 29 | 6 | 82.9% |
|  — + regular session | 29 | 15 | 14 | 51.7% |
|  — + HTF `trend_component = True` | 15 | **2** | 13 | 13.3% |
|  — + `risk_reward_ratio ≥ 1.5` | 2 | **1** | 1 | 50.0% |
| **Published signals** | 1 | 1 | 0 | 100% |
| **Trades executed** | 1 | **1** | 0 | 100% |

Candidate-level first-failure rejections (of the 7,646 non-published candidates):
`LOW_CONFLUENCE 5,290` · `OPENING_BLACKOUT 1,418` · `US_MARKET_SESSION_CLOSED 706` ·
`CLOSING_BLACKOUT 183` · `LOW_RISK_REWARD 15` · `PREMARKET_LIQUIDITY 6` · `TREND_GATE 3`.

**Two walls:** (1) the volatility gate removes **92.8%** of all bars before any trigger is even
evaluated; (2) of the 7,647 triggers that survive, the confluence gate passes **35** (0.46%) — and
after long-only + session + HTF-trend + R:R, exactly **one** reaches execution.

Signal-family mix of the 7,647 candidates: `macd_bullish_cross` 3,673 / `macd_bearish_cross` 3,535 /
`rsi_oversold_volume_surge` 152 / `rsi_overbought_volume_surge` 134 / `ma_death_cross` 78 /
`ma_golden_cross` 75 — **MACD crosses are 94%** of candidate volume; RSI (the family that ever cleared
confluence into the one trade) is ~4%.

### Segment B (Task 74S, same strategy) — for completeness
1,903,044 bars / 10 symbols / 1 year → **93.63%** bars `LOW_VOLATILITY`; 5,021 candidates; **72.5%**
`LOW_CONFLUENCE`; 12 bullish cleared confluence, 4 in regular session, all 4 failed HTF-trend or R:R
→ **0 bullish signals published, 0 trades.**

**Combined, all available history (~18.7 months, 35-symbol union, ~4.47M bars): 1 trade.**

## 2. Counterfactual — did each gate remove *good*, *bad*, or *noise* opportunities?

Method: for a population of bars/candidates, take the bar `close` as a hypothetical long entry and
measure raw forward return at +5 / +15 / +30 / +60 min and to session close (nearest bar within 10
min; EOD = last regular bar that ET day). This is a **descriptive forward-return** test, not a trade
sim — rejected events are never called "trades". Regular-session subsets shown (pre/after-hours are
structurally ineligible anyway).

### 2a. Volatility gate (`counterfactual_forward_returns.csv`)

| Population | n | +5m | +15m | +30m | +60m | EOD | EOD hit |
|---|---:|---:|---:|---:|---:|---:|---:|
| bars that **PASS** vol gate (regular) | 8,000 | +0.5 bps | +3.7 | +5.5 | +5.8 | **+30.3 bps** | 53.2% |
| bars that **FAIL** vol gate (regular) | 8,000 | −0.0 | +0.1 | −0.1 | +1.0 | **−1.3 bps** | 50.1% |
| random regular bar (null) | 8,000 | +0.5 | +1.3 | +1.4 | +2.3 | +0.2 bps | 49.7% |

**Finding:** the ~93% of bars the volatility gate rejects have **≈ zero forward long edge** (flat, ~50%
hit at every horizon — indistinguishable from the random null). The bars it *keeps* carry a small but
consistent positive drift, ~+30 bps by EOD at 53% hit. So on a *profitability* basis the 1-min
volatility gate is **removing mostly noise, not opportunity** — even though (Task 38) it is badly
misaligned with the product's *frequency* objective (it discards the large majority of genuine
RSI/MACD triggers, and it sits at ~the 90th percentile of all bars — `_volatility_threshold_sensitivity.csv`).
Caveat: the +30 bps EOD drift on passing bars is partly market beta over an up-trending 2025 H1;
un-risk-adjusted; single regime.

### 2b. Confluence gate (`counterfactual_forward_returns.csv`)

| Population | n | +5m | +15m | +30m | +60m | EOD |
|---|---:|---:|---:|---:|---:|---:|
| bullish, **confluence < 2**, regular (rejected) | 2,835 | +3.7 bps | +9.1 | +12.8 | +16.4 | +42.8 bps (52.9% hit) |
| bullish, **confluence ≥ 2**, regular (accepted) | **15** | **+31 bps** | **+114 bps** | +68 | +67 | −20.6 bps (40% hit) |

**Finding:** the 15 regular-session bullish candidates that *cleared* `confluence ≥ 2` had **markedly
stronger near-term continuation** — +114 bps at 15 min, 80% hit — than the LOW_CONFLUENCE-rejected
regular bullish population (+9 bps at 15 min, 52% hit). The confluence gate **is genuinely selective:
it picks candidates with real short-horizon edge.** But the edge is (i) **short-lived** — it fades and
turns *negative* by EOD (−20 bps), (ii) **tiny sample** (n=15, ~half from the April-2025 volatility
spike), and (iii) only **1 of those 15** also passed HTF-trend + R:R to become a trade. The
`confluence ≥ 2` set including pre-market/closed bars (n=29) is negative at most horizons — the signal,
such as it is, lives only in the regular-session subset.

## 3. What the funnel decomposition establishes

1. **Frequency bottleneck = volatility gate then confluence gate**, in that order, exactly as Tasks
   37/38/74S found and Task 92 observed live. The current frozen strategy produces **~1 executable
   long per 6.7 months per 35 symbols** — three orders of magnitude below the owner's
   `REGULAR_OPPORTUNITY` intent ("a few per week").
2. **The volatility gate is not destroying profitable setups** — the bars it rejects have no forward
   long edge. It *is* destroying frequency and (Task 38) genuine triggers. So "loosen the volatility
   gate" alone would add candidates with ~coin-flip forward returns, not alpha — it must be paired
   with a selection mechanism.
3. **The confluence gate looks like it works** — its 15 survivors had strong 15-60 min continuation.
   This is the single most encouraging signal in the study, and it is *fragile* (n=15, fades by EOD,
   one regime). It is a **Task 94 hypothesis area**, not a finding.
4. **HTF-trend + R:R then remove 14 of the last 15** — whether that is correct filtering or
   over-filtering is untestable here (n far too small); Task 94 area A4 (exit/geometry) and A2 (entry
   architecture) cover it.
