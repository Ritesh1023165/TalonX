# Task 118B Part 3 — regular-session readiness (2026-09-11, checked pre-open)

**Market has not opened at the time of this check** (13:30 UTC open; this
check performed at 12:39–12:55 UTC). Per this task's own instruction, what
follows is what is proven **now**, plus the exact observation still
needed after open — not a fabricated future result, and not a claim of
background monitoring.

## Preseed outcome, post-restart (11:54 UTC)

Substantially better than the earlier pre-restart 0/43 (Task 118A P2), but
**not** uniformly clean — traced directly from `original.log`:

| outcome | count (of 43) | evidence |
|---|---:|---|
| historical 1-min preseed succeeded (≥1 usable bar returned) | most symbols | `1-min historical pre-seed: loaded N bar(s)` lines, many at 120/120 |
| historical preseed returned **zero** data → live-accumulation fallback | at least BLK (confirmed) | `1-min historical pre-seed returned no data for BLK -- falling back to live accumulation`, same "possibly delisted" yfinance pattern as Task 118A P2 |
| historical preseed returned **very little** usable data (1 bar) | at least ADC (confirmed) | `1-min historical pre-seed: loaded 1 bar(s) for ADC` |

This confirms the practical impact varies **per symbol**, not
all-or-nothing — a materially different picture from "0/43 failed,
fallback caught everything."

## Current live-buffer readiness snapshot (12:39 UTC, ~51 min before open)

Queried directly against `quant.db.bar_buffer` (read-only):

- **18/43 symbols READY** (≥120 1-minute bars): AAPL, AFL, AGNC, AMAT,
  AMD, AVGO, GOOGL, INTC, MSFT, MSTR, NUE, NVDA, ORCL, SKHY, SPCX, STX,
  TSLA, VRT.
- **25/43 symbols NOT READY**, ranging from 118 bars (SHOP, 2 short) down
  to **1 bar** (ADC, BLK) — full per-symbol table:

| symbol | bars | latest bar (ET) | symbol | bars | latest bar (ET) |
|---|---:|---|---|---:|---|
| SHOP | 118 | 08:30 | UNH | 25 | 08:20 |
| WMT | 104 | 08:25 | ADP | 19 | 08:29 |
| BABA | 94 | 08:35 | MCD | 22 | 08:10 |
| CSCO | 85 | 08:30 | V | 14 | 07:40 |
| PYPL | 67 | 08:33 | IBM | 11 | 08:04 |
| DELL | 53 | 08:30 | BLSH | 10 | 08:00 |
| ABCL | 53 | 08:23 | C | 8 | 08:24 |
| ACHR | 45 | 08:35 | ABT | 7 | 07:45 |
| CVX | 39 | 08:26 | PG | 6 | 08:08 |
| KO | 33 | 07:55 | MA | 6 | 08:10 |
| JPM | 26 | 07:53 | JNJ | 3 | 08:30 |
| BAC | 24 | 08:33 | ADC | **1** | 06:15 |
| | | | BLK | **1** | 07:49 |

## Fallback: working, but not necessarily "soon enough"

**This is not called "expected behavior" merely because the fallback
mechanism exists** — its adequacy is checked against the clock, per this
task's own instruction. ADC's buffer has accumulated exactly **1 new bar
since 06:15 ET** (over 2.5 hours, thin pre-market trading in a
lower-liquidity REIT name — consistent with genuinely low premarket
volume for this ticker, not a stalled/broken process: `market:stream`
subscription is confirmed alive). At that observed rate, ADC (and
similarly BLK, JNJ, V, IBM, C, ABT, PG, MA) has **no realistic path to
120 bars via 1-min-bar-per-tick live accumulation before the 13:30 UTC
open** — the required ~119 additional bars in ~51 minutes would need
close to one new bar per real minute of premarket activity, which these
specific thin names are not producing. **This is a genuine, quantified,
practical readiness gap for roughly half the 43-symbol scope**, not
resolved by the fallback's mere existence.

## Distinguishing readiness-blocked from LOW_VOLATILITY

`quant.db.suppression_counts` for **today** (2026-09-11) already shows
`LOW_VOLATILITY: 72 suppressions across 14 distinct tickers` — meaning 14
tickers have already reached the volatility-gate evaluation stage at
least once today (necessarily requiring ≥120 bars to be evaluated at
all). **Zero** suppression-count rows exist today for any of the 25
currently-not-ready symbols — they have not been evaluated even once,
not "rejected." This directly answers the distinction this task requires:
the 25-symbol gap is a **readiness** gap, not a volatility-selectivity
outcome, and the two are not being conflated here.

## No opportunity-cost claim made

No causal candidate or forward-price evidence exists (or was sought) to
support a claim that a profitable opportunity was missed because of this
gap — none is made. This section reports a readiness/coverage gap only.

## Implementation defect assessment

**No specific, bounded, safe code defect was found to fix.** The gap
traces to (a) yfinance's own intermittent bulk-fetch failures (external,
already documented in Task 118A P2) and (b) genuinely thin real premarket
liquidity in specific names (a market characteristic, not a bug). A retry
-with-backoff on the historical preseed fetch, or a secondary data source
for thin names, would be a **new resilience feature**, not a fix to a
proven defect — out of scope here without further review, and not
attempted. No threshold was lowered, no history requirement was reduced,
and no bars were manufactured to make this status appear green.

## What is still needed — explicitly not fabricated here

Whether the 25 currently-gapped symbols reach readiness by 13:30 UTC, and
whether any of them are actually evaluated (LOW_VOLATILITY or otherwise)
during the early regular session, **requires observing the actual
regular-session state after 13:30 UTC** — not available at the time of
this report. **This observation gap is the explicit deliverable of this
section, not an omission.**

## Evidence

`quant.db.bar_buffer`, `quant.db.suppression_counts` (read-only, this
session); `results/task100b_runtime_integration/_supervisor_logs/original.log`
(post-restart preseed lines, timestamped).
