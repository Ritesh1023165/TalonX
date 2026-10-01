# TASK 93 — Phase 8: Concentration Analysis

Segment A replay. **Trade-level concentration is degenerate: n = 1 trade** (PYPL, 2025-04-30,
`rsi_oversold_volume_surge`, +5.99 R at 0 bps, EOD exit). One trade is by definition 100% concentrated
in one symbol, one month, one signal-family, one regime. There is **no distribution to analyse** — a
single observation cannot tell you whether "one symbol / month / regime creates the apparent edge",
because there *is* no repeatable edge to attribute. This is the finding.

Everything below is therefore at the **candidate** and **rejection** level (7,647 candidates), which is
where structure can be seen.

## By symbol (candidates that passed the volatility gate)

`_candidate_concentration_by_symbol.csv`. Top by candidate count:
TSLA 813 · INTC 539 · NVDA 485 · AVGO 457 · LRCX 436 · MU 429 · AMD 400 · AMAT 288 · STX 269 · PANW 245.
Top-5 = **35.7%** of all candidates; all 35 symbols produced at least some. Candidate volume tracks
realised intraday volatility (the higher-beta semis/TSLA dominate) — the same pattern Task 26/36/74S
saw (STX/AMD carrying raw candidate volume). **The one trade (PYPL) is not one of the high-candidate
names** — it is the lone case where a lower-volume name's RSI candidate happened to clear every gate.

## By month

`_candidate_concentration_by_month.csv`:

| Month | Candidates | Share |
|---|---:|---:|
| 2025-01 (partial) | 388 | 5.1% |
| 2025-02 | 742 | 9.7% |
| 2025-03 | 1,316 | 17.2% |
| **2025-04** | **3,819** | **49.9%** |
| 2025-05 | 482 | 6.3% |
| 2025-06 | 265 | 3.5% |
| 2025-07 | 419 | 5.5% |
| 2025-08 (partial) | 216 | 2.8% |

**Half of all candidates over 6.7 months came from a single month — April 2025** (the tariff-shock
volatility spike). The volatility gate only opens meaningfully when realised 1-min volatility is
extreme; outside that spike the funnel is nearly dead. The one trade is also in April 2025. So *what
little the strategy does* is overwhelmingly a **volatility-regime-conditional** phenomenon concentrated
in one stressed month — not a steady-state edge.

## By year / regime

- **Only 2025 H1 is covered by Segment A** — a single macro arc (rally → April tariff shock/drawdown →
  recovery). Segment B (Task 74S, 2025-08 → 2026-08) adds regime variety but produced **0 trades**, so
  it contributes nothing to a per-regime trade breakdown.
- Deterministic regime split available: `passes_volatility` True/False (high vs low 1-min volatility).
  Candidates (and the one trade) are ~entirely in the **high-1-min-volatility** state — by construction
  of the gate. No trending-vs-ranging or risk-on/risk-off split is meaningful at n=1.
- No AI-derived regime classifier used (task instruction).

## Contribution to result

| Dimension | Concentration |
|---|---|
| Symbol | 100% PYPL (n=1) |
| Month | 100% April 2025 (n=1) — and 49.9% of all *candidates* also April 2025 |
| Signal family | 100% `rsi_oversold_volume_surge` (n=1) — though RSI is only ~4% of candidate volume; MACD (94%) never produced a trade |
| Regime | 100% high-1-min-volatility state (n=1) |
| Exit path | 100% `END_OF_SESSION` (n=1) |

## Conclusion

There is **no edge to concentrate**. The single trade is fully explained by one symbol, one month, one
regime — which is exactly what "n=1" means. At the candidate level, the only visible structure is that
the strategy's activity is **extremely time-concentrated in the April-2025 volatility spike** and
**MACD-dominated in volume but RSI-dependent for the one trade**. Any future evaluation must treat
April 2025 as a potential single-month artifact, not a representative sample.
