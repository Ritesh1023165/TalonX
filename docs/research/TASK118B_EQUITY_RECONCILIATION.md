# Task 118B Part 2 — corrected equity and drawdown (2026-09-11)

**Withdraws** the "portfolio-drawdown" label previously attached to
−$23,042.30 / −0.23% ($10m) and −7.68% ($300k) in
`TASK118A_RESEARCH_CORRECTIONS.md` Correction 2. Replaced with a real,
mark-to-market chronological equity series.

## What `portfolio_cash_after` actually measures — traced to source

`portfolio_cash_after` (the field the withdrawn figure was built from) is
literally **uninvested cash only** — `talonx_research.replay_engine`'s
ledger (mirroring `talonx_v2.service.V2Service`'s own accounting)
decrements it by the full position cost at entry and credits it by sale
proceeds at exit; it is never adjusted for the market value of a position
while it is *held*. **Buying an asset reduces cash by its cost without
creating an equivalent immediate economic loss** — the $10,000 leaves
cash and becomes $10,000 of VRT/MSTR/etc. stock, not $10,000 of
disappeared value. Labelling a dip in this field a "portfolio drawdown"
overstates real risk: it counts every entry as if it were a loss, and
only the network of overlapping entries/exits happened to make the
mislabeled figure numerically large. Relabelled here as **cash-path
drawdown** where that number is still useful (e.g. for capacity/liquidity
planning — how much of the campaign's own cash was tied up at any point),
explicitly distinct from portfolio drawdown.

## Corrected chronological equity

`equity(t) = cash(t) + Σ shares_i × mark_price_i(t)` for every open
position `i`, built day-by-day over the full 2024-09-01→2026-03-31 window,
using:
- **Entry/exit cash events** dated on the trade's own entry/exit session,
  cost applied **exactly once** per round trip (`net_ret = gross_ret −
  20bps`, the same convention `reconcile.py` already used — verified to
  reconcile to the cent, see below).
- **Timestamped marks**: the entry price on the entry day, the exit price
  on the exit day, and the local daily-bar CSV close (frozen,
  `task95g_broad_cross_sectional/_daily` / `task107a_form4_feasibility/_prices`
  — the SAME static data the baseline replay itself used) for every day
  strictly between. **No future price was ever used** — each day's mark
  is that day's own close, sourced only from data dated at or before it.
- **Calendar**: the union of every date any of the 6 involved symbols
  (ACHR, MSTR, UNH, ADC, ABT, IBM) has a bar for, used as the trading-day
  index — every date in this series is therefore a date the underlying
  price data itself already treats as a session.
- **Missing marks**: **zero** — full daily coverage existed for all 6
  symbols across every day any position was held; no fallback was needed
  and none was silently substituted. (Had a gap existed, it would be
  reported as a labelled fallback, not hidden — the script logs any such
  case explicitly.)

This is a **daily-close-based** equity series — it can only show
**daily-close-to-daily-close drawdown**, not true intraday drawdown; that
distinction is stated here explicitly, not implied.

## Corrected metrics

| base | final equity | final − starting | matches summed trade-level net P&L | max drawdown ($) | max drawdown (%) | peak date | trough date |
|---|---:|---:|---|---:|---:|---|---|
| $10,000,000 | $9,997,073.85 | **−$2,926.15** | **exact match** | **−$7,132.76** | **−0.0713%** | 2024-11-29 | 2025-08-01 |
| $300,000 | $297,073.85 | **−$2,926.15** | **exact match** | **−$7,132.76** | **−2.3560%** | 2024-11-29 | 2025-08-01 |

**Capital constraints and executed trades are confirmed identical** across
both bases — same 10 trades, same entry/exit prices, same dollar P&L path
(already established in Task 118A: max concurrent notional was only
$20,000, far under either budget, so neither base was ever capacity-
constrained; this equity build reconfirms it independently by construction
— the two bases differ only in their starting-cash constant, and the
resulting equity paths are parallel, offset by exactly $9,700,000).

## Contrast with the withdrawn cash-path figures

| measure | $10m | $300k |
|---|---:|---:|
| withdrawn cash-path "drawdown" (Correction 2, Task 118A) | −0.23% | −7.68% |
| **corrected real equity drawdown** | **−0.0713%** | **−2.3560%** |

The real, mark-to-market drawdown is meaningfully **smaller** than the
withdrawn cash-path figure at both bases — confirming the withdrawn label
overstated the campaign's actual peak-to-trough economic loss, exactly as
Part 2 anticipated ("buying assets reduces cash without creating an
equivalent immediate economic loss"). Both remain far smaller than the
unrelated −42.7% cumulative-trade-return running-sum figure (a third,
already-distinguished quantity — unchanged from Task 118A's Correction 2,
which correctly separated it from either cash-path or equity drawdown).

## Peak/trough and position contributions

Peak equity (2024-11-29, both bases) occurred one session after the first
trade's entry (ACHR, 2024-11-27), while its mark briefly rose before its
eventual loss. Trough (2025-08-01) falls during MSTR's third position
(entered 2025-07-30, held through its own decline) — MSTR contributes the
dominant share of the drawdown path, consistent with its already-
documented 64% share of absolute closed-trade P&L (Task 118 Part 2C).

## Reproducible script and manifest

`results/task118_profitability/build_equity_curve.py` (checked in) —
reads `reconciliation/trades.csv` (already-published, sanitized) plus the
same frozen local daily-bar CSVs under `C:\workspace\TalonX\results\`
(read-only, static, not live/production data). Outputs
`reconciliation/equity_curve_10m.csv` and `equity_curve_300k.csv`
(checked in, sanitized — date/cash/open_value/equity/peak/drawdown_usd/
drawdown_pct only, no account or API identifiers).

## Evidence files

`results/task118_profitability/build_equity_curve.py`,
`reconciliation/equity_curve_{10m,300k}.csv` — all checked in.
