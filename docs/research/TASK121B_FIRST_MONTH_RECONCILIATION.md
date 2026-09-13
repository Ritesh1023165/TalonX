# Task 121B Part 1 — first-month complete portfolio reconciliation

Read consistently from the salvaged authoritative ledger
(`docs/research/evidence/task121a/month1_corrected_SALVAGED.json`, itself
read directly off `ExperimentalPaperEngine`'s own SQLite
`trade_history`/`positions`/`portfolio_state` tables at the end of the
2025-01-24→2025-02-23 replay). No number below is recomputed by a
different method than the one that produced the original $61.92 figure —
this document verifies and decomposes it, it does not replace it.

## Complete portfolio state at month end

| | |
|---|---:|
| Starting capital | $100,000.00 |
| Entries (BUY rows) | 33 |
| Closed round trips (SELL rows) | 33 |
| **Remaining open positions** | **0** |
| Ending cash | $100,061.92 |
| Marked open-position value | $0.00 (0 positions to mark) |
| **Ending equity (cash + marked open value)** | **$100,061.92** |

**Verification, not assertion**: 33 entries = 33 closed round trips = 0
open positions. Because there is nothing left open, `equity = ending_cash`
exactly, and `ending_cash = starting_capital + net_pnl_usd_total`
($100,000.00 + $61.925 = $100,061.925, matching the ledger's own
`current_cash` to the sub-cent). **For this specific month, +$61.92
closed-trade P&L IS the complete total portfolio profit** — verified by
the zero-open-position fact, not assumed from the closed-trade figure
alone. This will NOT automatically hold for the Segment A extension (Part
6), where open positions at the window boundary are expected and will be
reported separately (marked, not netted into "closed" P&L).

No forced terminal liquidation occurred and none was needed (0 open at
cutoff). No unresolved valuations for this month.

## Gross / cost / net decomposition

Recomputed directly from each trade's own stored `entry_price`/
`execution_price` (both already spread-inclusive fills) by inverting
`apply_spread`'s known formula (`raw = fill / (1 ± bps/2/10000)`) — not a
new spread assumption, the same 5.0bps `ExperimentalPaperEngine` default
already used to produce the fills.

| | |
|---|---:|
| Gross P&L (pre-spread) | **+$103.19** |
| Embedded spread cost (33 trades × ~2×2.5bps on $2,500 notional) | **−$41.27** (≈ $1.25/trade × 33 = $41.25, matches to the cent) |
| **Net P&L (matches the ledger exactly)** | **+$61.93** (ledger: $61.925) |
| Commissions/fees | not modeled (unchanged from every prior finding this session) |

## Win/loss, largest trades, concentration

| | |
|---|---:|
| Wins | 7 (21.2%) |
| Losses | 26 (78.8%) |
| Average win | +$75.66 |
| Average loss | −$17.99 |
| Largest winner | INTC, +$179.22, exit 2025-02-18 10:36 UTC |
| Largest loser | PANW, −$57.59, exit 2025-02-20 14:33 UTC |
| Distinct issuers | 18 |
| Max trades from one issuer | 3 (AMAT, MU, LRCX, STX — each 3/33 = 9.1%) |

The small-win-count/high-average-win, large-loss-count/small-average-loss
shape (7 wins averaging +$75.66 vs. 26 losses averaging −$17.99) is
consistent with a stop/target-bracket contract where the reward:risk
ratio gate (≥1.0) admits asymmetric-payoff trades — expected given the
contract's own geometry, not a data artifact.

## Holding-period distribution and overnight/weekend exposure

| | |
|---|---:|
| Min hold | 180s (3 minutes) |
| Max hold | 603,000s (**6.98 days**) |
| Mean hold | 74,536s (**20.7 hours**) |
| Trades crossing a calendar-date boundary (overnight/weekend) | **14 / 33 (42.4%)** |

The ~7-day maximum and 42% overnight-crossing rate are direct, positive
evidence (not merely a source-code reading) that the Part 2 corrected
contract (no EOD flatten, no bearish-signal close) is what actually
produced this run — a 15:50-ET-forced-flatten lifecycle could never
produce a multi-day hold at all.

## Marks and adjustment basis

Not applicable this month — 0 open positions at cutoff, so no marked
valuation was required. Marking methodology (last available close in the
replay window, Alpaca 1-min UNADJUSTED, same basis as every fill) is
specified and will be exercised for real in Part 6, where the Segment A
window is expected to end with open positions.
