# TASK 95A — Phase 2 — Target History Specification

**Pre-registered BEFORE any profitability inspection.** Start/end dates chosen for *regime
diversity*, not for backtest results. This document is frozen once written; Phase 6 checks whether
the acquired data actually delivers the regime diversity claimed here.

## Target

| Field | Value |
|---|---|
| Period | **2020-01-01 → 2026-08-14** (~6.6 years) |
| Universe | Task 93 35-symbol set (unchanged — added/removed for comparability only, never for profitability) |
| Granularity | 1-minute OHLCV |
| Provider | Alpaca Market Data v2 (`data.alpaca.markets/v2/stocks/{symbol}/bars`) |
| Feed | **SIP** (matches Task 93 canonical; `feed` omitted → resolves to SIP on this account) |
| Adjustment | `raw` (UNADJUSTED) — identical to Task 93 |
| Sessions | Extended hours included (pre-market + after-hours), UTC tz-aware — identical to Task 93 |
| Already local | 2025-01-24 → 2026-08-14 (Task 93 canonical) — **spliced, not re-downloaded** |
| To acquire | **2020-01-01 → 2025-01-23**, all 35 symbols |

## Why this period — regime pre-registration

The minimum objective (spec) is to include regimes substantially different from 2025 H1 (Task 94's
only macro regime). Target periods and the *a priori* regime each is expected to contribute:

| Sub-period | Expected regime (declared before measurement) |
|---|---|
| 2020-01 → 2020-03 | Pre-COVID melt-up, then the **COVID crash** (fastest bear on record, extreme volatility) |
| 2020-04 → 2020-12 | **V-shaped recovery / liquidity-driven bull**, mega-cap leadership |
| 2021 | **Retail/meme bull**, low-vol grind higher, periodic single-name volatility spikes |
| 2022 | **Bear market / high-rate regime** — sustained drawdown, elevated realized vol, failed rallies |
| 2023 | **Recovery / trend regime** — disinflation rally, breadth narrow then widening |
| 2024 | **AI-led momentum bull** — strong trend, semis leadership, low realized vol |
| 2025-01 → 2025-08 | 2025 H1 — mixed / **tariff-shock volatility** (April 2025), the Task 94 discovery window |
| 2025-09 → 2026-08 | Later 2025–2026 (deep-10 only) — Task 93 validation + holdout span |

This spans **at least 6 qualitatively distinct macro regimes** and multiple independent
volatility cycles, versus Task 94's single 2025-H1 regime. Phase 6 will confirm with deterministic,
non-optimized regime labels (trend / realized-vol / drawdown-state / year / quarter).

## Coverage caveats accepted in advance

- **Split discontinuities** in unadjusted data: notably NVDA 10-for-1 (2024-06-10), AMZN 20-for-1
  (2022-06-06), TSLA 3-for-1 (2022-08-25) and 5-for-1 (2020-08-31). Each will appear as a single-bar
  step and is handled in Phase 5 (documented, and forward-return features are computed as
  intra-day % returns that are immune to a between-day split step except on the split day itself,
  which is flagged/excluded).
- **Listing dates**: PANW, AVGO, ISRG, REGN, BKNG etc. all trade well before 2020, so no IPO gaps
  are expected inside 2020-2026 for this universe. Any symbol with <95% expected coverage in a
  period is reported, not backfilled.
- **Deep vs common history**: only 10 symbols (AAPL AMD AMZN GOOGL META MSFT NVDA PYPL STX TSLA)
  have data past 2025-08-14. Full 35-symbol coverage exists 2020-01 → 2025-08-14. A
  **COMMON_UNIVERSE** (the 10 deep names, full 2020→2026 span) is reported alongside the full
  universe so survivorship/coverage changes cannot masquerade as regime effects.
- **SIP vs IEX**: Task 93 and this expansion are both SIP → no feed-provenance split. (IEX 1-min
  history only starts 2020-07-27 on this account and is not used.)
- **No further-back extension**: SIP would serve 2016+, but 2020-01-01 already covers a crash, a
  liquidity bull, a bear, a recovery and a momentum bull — the pre-registered objective. Not
  extending to 2016-2019 keeps acquisition/compute bounded and avoids a pre-universe-relevance era.
