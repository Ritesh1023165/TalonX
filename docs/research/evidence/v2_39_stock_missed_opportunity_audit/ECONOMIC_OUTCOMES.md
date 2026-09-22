# Economic outcomes (computed only after classification)

These figures are **all HYPOTHETICAL**. There were 0 actual intents, fills or trades in V2-PAPER-RC1, so there is no ACTUAL row. Profitability validation: **NOT_COMPLETE**. Two hypothetical, pre-campaign data points prove nothing about the strategy.

Basis:
- Frozen release rules, the Alpaca SIP `1Day` provider with split-only adjustment and no fallback, fetched through the frozen `talonx_v2.sip_adapter.AlpacaSipBarAdapter` (read-only GET at 2026-09-22 21:00:07Z)
- Frozen `talonx_v2.liquidity`, `talonx_v2.sizing` (zero-fee frozen assumption) and `talonx_v2.corporate_actions` (Alpaca `v1/corporate-actions`)
- Entry at the entry-session **open**; exit at the **close** 10 sessions later (`pipeline.py:138,283`)
- Bar finality follows the frozen contract (usable only once now ≥ close + 4h + 16min): 09-21 and earlier are FINAL, 09-22 was **PROVISIONAL** at fetch time.

Raw values: `extracts/economics_and_price_context.json`.

## 1. Per-opportunity (classified `MISSED_DUE_TO_INGESTION_DOWNTIME`)

| Field | ABCL `07242bc857569f60` | ADC `19f814d1f3ec3250` |
|---|---|---|
| Label | HYPOTHETICAL: closed (exit session reached) | HYPOTHETICAL: open (exit session not reached) |
| In core window 09-16..09-22 | no (pre-campaign, lookback only) | **yes** (pre-campaign) |
| Intended entry session | 2026-08-17 | 2026-09-18 |
| Liquidity gate (frozen) | PASS: last close $11.38, 20-session MDV $32,399,585 | PASS: last close $68.16, 20-session MDV $93,603,743 |
| Authoritative entry price (open, FINAL) | $11.30 | $68.27 |
| Whole shares from $10,000 | 884 | 146 |
| Capital used (fee-inclusive) | $9,989.20 | $9,967.42 |
| Intended exit session | 2026-08-31 | 2026-10-02 (not reached) |
| Exit / mark price | $11.48 (08-31 close, FINAL) | MTM $67.62 (09-21 close, FINAL); $67.32 (09-22 close, PROVISIONAL) |
| Dividends | none (no corporate action in the window) | none. The only ADC event is a $0.267 cash dividend with ex-date 2026-08-31, before entry, so there is no entitlement. |
| P&L | **+$159.12 realized-hypothetical** | **−$94.90 unrealized** (FINAL mark); −$138.70 on the PROVISIONAL mark |
| Return % | **+1.59%** | **−0.95%** (FINAL); −1.39% (PROVISIONAL) |

## 2. Totals (HYPOTHETICAL only)

| Scope | Opportunities | Capital | Realized-hypothetical | Unrealized-hypothetical (FINAL mark) | Net | Return |
|---|---|---|---|---|---|---|
| Core window 09-16..09-22 (ADC only) | 1 | $9,967.42 | $0.00 | −$94.90 | −$94.90 | −0.95% |
| Full 45-day lookback (ABCL + ADC) | 2 | $19,956.62 | +$159.12 | −$94.90 | +$64.22 | +0.32% |

ADC's final hypothetical outcome is **UNKNOWN** until the 2026-10-02 close. It can be completed then, still labelled HYPOTHETICAL.

## 3. Session 02 price context for the 39 symbols (CONTEXT ONLY)

These are ordinary price moves, not V2 opportunities. None of these symbols had a qualifying insider cluster whose actionable window touched Session 02.

| Symbol | Prior close 09-21 (final) | Open 09-22 | Close 09-22 (provisional) | Move vs prior close |
|---|---|---|---|---|
| AAPL | 338.98 | 340.135 | 339.75 | +0.23% |
| ABCL | 12.66 | 12.56 | 12.65 | -0.08% |
| ABT | 102.98 | 104.01 | 103.69 | +0.69% |
| ACHR | 5.43 | 5.6 | 5.69 | +4.79% |
| ADC | 67.62 | 67.66 | 67.32 | -0.44% |
| ADP | 269.94 | 271.18 | 269.64 | -0.11% |
| AFL | 115.18 | 115.02 | 114.6 | -0.50% |
| AGNC | 9.97 | 10.04 | 10.09 | +1.20% |
| AMAT | 464.24 | 457.9 | 472.46 | +1.77% |
| AMD | 615.52 | 606.565 | 623.77 | +1.34% |
| AVGO | 362.66 | 363.23 | 364.54 | +0.52% |
| BAC | 57.96 | 58.1 | 56.2 | -3.04% |
| BLK | 1090.27 | 1089.94 | 1066.66 | -2.17% |
| C | 135.05 | 134.87 | 132.47 | -1.91% |
| CSCO | 111.46 | 110.275 | 106.44 | -4.50% |
| CVX | 203.67 | 201.87 | 202.41 | -0.62% |
| DELL | 575.31 | 569.8 | 548.92 | -4.59% |
| GOOGL | 354.97 | 357.65 | 351.16 | -1.07% |
| IBM | 231.93 | 234.47 | 231.38 | -0.24% |
| INTC | 121.78 | 120.15 | 123.86 | +1.71% |
| JNJ | 269.47 | 267.51 | 269.19 | -0.10% |
| JPM | 352.04 | 352.0 | 340.0 | -3.42% |
| KO | 87.12 | 87.6 | 88.61 | +1.71% |
| MA | 567.65 | 571.18 | 555.89 | -2.07% |
| MCD | 247.88 | 250.68 | 250.35 | +1.00% |
| MSFT | 501.61 | 507.32 | 498.0 | -0.72% |
| MSTR | 168.5 | 167.545 | 167.33 | -0.69% |
| NUE | 242.4 | 241.5 | 245.66 | +1.34% |
| NVDA | 227.38 | 226.85 | 228.87 | +0.66% |
| ORCL | 148.56 | 151.25 | 149.2 | +0.43% |
| PG | 146.08 | 147.42 | 148.22 | +1.46% |
| PYPL | 52.62 | 53.2 | 52.89 | +0.51% |
| SHOP | 137.92 | 144.55 | 147.74 | +7.12% |
| STX | 877.325 | 857.69 | 919.84 | +4.85% |
| TSLA | 375.3 | 379.069 | 378.9 | +0.96% |
| UNH | 377.56 | 381.39 | 372.95 | -1.22% |
| V | 369.95 | 371.76 | 362.04 | -2.14% |
| VRT | 250.86 | 250.3 | 253.46 | +1.04% |
| WMT | 107.44 | 108.12 | 110.12 | +2.49% |