# Task 121B — extended Experimental replay: results and decision

Protocol frozen in `docs/research/TASK121B_EXTENDED_PROTOCOL.md` before
this replay was executed against real outcomes. Reliability fix and its
verification: `docs/research/TASK121B_RELIABILITY_FIX.md`. First-month
reconciliation (already-published Task 121A figures, verified complete):
`docs/research/TASK121B_FIRST_MONTH_RECONCILIATION.md`. Adapter:
`research/scripts/task121b_reliable_replay.py`, run_id
`segmentA-full-2025-01-24_2025-08-14`.

## Part 6 — the fixed run

**Window**: `2025-01-24` → `2025-08-14` inclusive (Segment A_broad,
exactly as recorded in `canonical_dataset_manifest.json`), all 35
symbols, run as ONE continuous replay from its own start (per Part 4 —
no checkpoint existed from the first-month run, so it is not resumed or
stitched).

**Status**: `COMPLETE`. **2,565,682 bars** processed (100%), 0 gaps
against the frozen manifest. Backtest itself: **40,633.7 seconds
(~11.29 hours)**. Summary generation: **~181 seconds** (40,815.1s total
− 40,633.7s) — a bounded SQL-aggregate operation, not the old adapter's
indefinite hang; the reliability fix held under the real, full-scale
run, not just the earlier 2-week verification. No abandoned duplicate
processes (verified after completion).

## Part 7 — results

### Funnel

| stage | count |
|---|---:|
| Bars processed | 2,565,682 |
| Raw candidates (`evaluate_signals`, pre-gate) | 46,905 |
| Rejected: LOW_VOLATILITY | 1,490,039 |
| Rejected: LOW_CONFLUENCE | 29,977 |
| Rejected: LOW_RISK_REWARD | 2,245 |
| Rejected: TREND_GATE | 802 |
| Rejected: HTF_DATA_UNAVAILABLE | 47 |
| Rejected: OPENING_BLACKOUT | 4,060 |
| Rejected: CLOSING_BLACKOUT | 1,609 |
| Rejected: US_MARKET_SESSION_CLOSED | 4,295 |
| Rejected: PREMARKET_LIQUIDITY | 765 |
| Rejected: COOLDOWN | 1,056 |
| Rejected: THROTTLE | 98 |
| Rejected: NO_ACTIVE_POSITION (bearish, nothing open) | 1,606 |
| **Published (engine's own counter)** | **1,934** |
| Published, direction bearish | 67 |
| Published, direction bullish | 261 |
| — of which OPENED | 229 |
| — of which SKIPPED_POSITION_ALREADY_OPEN | 32 |
| — of which BEARISH_PUBLISHED_WHILE_OPEN (no action) | 67 |
| **Closed round trips** | **227** |
| **Open/unresolved at window end** | **2** (GOOGL, MU) |

**Reconciliation, not inference**: 1,934 published − 261 bullish − 67
bearish = 1,606, exactly matching `NO_ACTIVE_POSITION` — every published
signal is accounted for by direction and disposition from real,
per-event telemetry (Task 121's original limitation — inferring
direction from equality of aggregate counters — does not apply here).
229 OPENED + 2 still-open-at-window-start-of-window-end is not quite
227 closed + 2 open = 229 total entries, exactly matching OPENED. Exit
reasons (fine-grained, from the shim's own log): **183 stop_loss, 44
target_exit** — the SQL ledger's own coarse column stores all 227 as
`confirmed_bearish` (AlertAction), same disclosed distinction as Task
121A.

### Economics

| | |
|---|---:|
| Closed round trips | 227 |
| Distinct issuers | **35 of 35** (every configured historical symbol traded at least once) |
| Gross P&L (pre-spread) | **−$612.92** |
| Embedded spread cost (227 × ~$1.25) | **−$283.53** |
| **Net P&L (closed trades)** | **−$896.44** |
| Win rate | 19.4% (44/227) |
| Average win | +$66.00 |
| Average loss | −$20.77 |
| Profit factor | **0.764** |
| Net expectancy (mean $/trade) | **−$3.95** |
| Largest winner | INTC, +$179.22 (2025-02-18) |
| Largest loser | ISRG, −$146.12 (2025-04-21) |
| Holding duration | min 60s — max 958,800s (**11.1 days**) — mean 72,432s (**20.1 hours**) |
| Overnight/date-crossing trades | 75/227 (33.0%) |

**Gross P&L is already negative before any modeled cost** — this
contract does not merely lose to transaction friction, its raw signal
geometry lost money over this window even at a hypothetical zero-cost
execution.

### Equity (cash + marked open-position value — never a cash-only or
   cumulative-return substitute)

| | |
|---|---:|
| Starting capital | $100,000.00 |
| Ending cash | $94,103.56 |
| Open positions at cutoff | 2 (GOOGL 12.44 sh @ $200.89 entry, stop $200.00/target $205.03, marked $202.89 → $2,524.89; MU 20.13 sh @ $124.18 entry, stop $122.19/target $127.44, marked $125.50 → $2,526.65) |
| Marked open-position value | $5,051.54 |
| **Ending equity** | **$99,155.10** |
| **Total portfolio P&L (equity − starting capital)** | **−$844.90** |

Both open positions carry a small unrealized GAIN ($24.89 and $26.65
respectively — neither is an "open loser" being excluded; both are
included in the equity figure above, per this task's explicit
instruction). Neither position is force-closed; both are marked at the
last available close in-window (2025-08-14, Alpaca 1-min UNADJUSTED,
same basis as every fill) and reported as genuinely unresolved
obligations — their eventual real outcome is unknown.

### Concentration and time sensitivity (predeclared)

- By issuer: LRCX and STX lead with 15 trades each; AVGO 14; no issuer
  exceeds 6.6% of trades.
- **Drop-top-1-issuer (LRCX, 15/227)**: mean moves from −$3.95 to
  **−$5.33/trade** — MORE negative, not less; the result is not being
  propped up by one issuer.
- **Split-half by trade sequence** (first 113 vs. last 114 trades,
  chronological): first half mean **−$10.97/trade**; second half mean
  **+$3.01/trade**. The full-window result is NOT uniform across time —
  the first ~3.3 months were substantially worse than the second
  ~3.4 months, which was mildly positive. Reported explicitly per the
  predeclared time-concentration sensitivity, not smoothed over.

### Uncertainty (predeclared: issuer-block bootstrap, 5,000 reps, seed
   121121, 95% percentile CI — same convention/seed as Task 121A)

**95% CI on net $/trade: [−$8.94, +$1.06].** Effective independent-group
count: **35 issuers** (not 227 trades).

### Execution-realism sensitivity (predeclared: next-available-bar-close
   fill, chronologically propagated)

All 227 trades re-priced at the next available bar's own close after the
primary entry bar (shares/P&L fully recomputed from the delayed price,
not a constant subtraction — 0 trades dropped for landing outside a
valid fill-geometry bracket):

| | primary (signal-bar-close) | sensitivity (next-bar-close) |
|---|---:|---:|
| Net P&L total | −$896.44 | **−$927.91** |
| Mean $/trade | −$3.95 | **−$4.09** |

**Delta: −$31.46 total, sign unchanged.** The 1-bar execution-latency
sensitivity makes the result marginally MORE negative, not less —
confirms the primary finding is not an artifact of the zero-latency
fill assumption.

### First month vs. extension vs. continuous-campaign total

| | first month (Task 121A) | extension (this run's remainder) | **full continuous campaign (this run)** |
|---|---:|---:|---:|
| Window | 2025-01-24→02-23 | 2025-02-24→08-14 (not separately re-run — see note) | **2025-01-24→08-14** |
| Closed trades | 33 | — | **227** |
| Net $/trade mean | +$1.88 | — | **−$3.95** |
| 95% CI ($/trade) | [−$12.36,+$16.88] | — | **[−$8.94,+$1.06]** |

Per Part 4's own instruction, the "extension" was **not** run as a
separate, independently-stitched portfolio — the full window above is
ONE continuous replay from its own start, superseding (not averaging
with, not stitching to) the standalone first-month figure. The
first-month column is retained here ONLY as a before/after reference
point showing how the estimate sharpened and changed sign with ~7×
more data, not as a component of the campaign total.

**Recovery-affected live exits** (the four 2026-09-11 Experimental
exits) are, as in every prior task, **not pooled into this historical
study** — this replay uses only `task93_canonical_v1` historical bars,
never the live ledger.

**Frequency**: 227 trades over 6.7 months ≈ 34/month — consistent with
(not merely a restatement of) Task 121A's single-month rate; this run
does NOT claim monthly frequency is "stable" from one observation — it
is now observed across 7 different calendar months (Jan 24-tail through
Aug 14-partial) with the split-half analysis above showing real
period-to-period variation in the ECONOMIC outcome, not the frequency.

## Decision

**`INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`**

Per the protocol's own predeclared, symmetric rule (§9): `ADVANCE`
requires the 95% CI to clear +$1.25/trade on the low side; `REJECT`
requires it to clear −$1.25/trade on the high side. This run's CI is
**[−$8.94, +$1.06]** — the lower bound clears the negative materiality
band, but the **upper bound ($1.06) does not** clear it (it stays
inside the ±$1.25 zone, and the interval as a whole still spans zero).
Neither criterion is met.

**This is not a hedge.** The weight of the POINT evidence leans clearly
negative — gross P&L is negative BEFORE any cost, PF is 0.76, win rate
is 19.4%, the point estimate is −$3.95/trade, and removing the largest
single issuer makes it worse, not better. What keeps this from clearing
the predeclared REJECT bar is exclusively the resampling uncertainty
across only 35 independent issuer groups — a real, named, specific
statistical limit, not an excuse to relabel a bad number as
inconclusive-and-neutral.

**Exact blocker**: 35 independent issuer-groups is the entirety of
`task93_canonical_v1`'s available symbol population — there is no more
SAME-population historical data to add. Segment B_deep (10 symbols,
2025-08-15 onward) is a DIFFERENT, smaller, differently-sourced dataset,
not a drop-in extension, and is out of this task's authorized scope.
**Further historical backtesting of this exact question, on this exact
data asset, is exhausted** — this is stated plainly, not glossed over
as "run it again."

**Is resolving this worth further effort within the existing roadmap?**
No, not via more backtesting of the same data. The evidence, taken as a
whole, does not support proceeding to costlier further validation
(paper-capital scaling, live promotion) for `EXPERIMENTAL_RELAXED_V1`
on this basis. If the owner wants a genuinely NEW information source
resolving this specific uncertainty, the only one available without new
data acquisition is continued LIVE forward observation under the now-
corrected, verified-wired exit lifecycle (Task 118A's `check_exits` fix)
— which is a live-operations decision, not a backtest, and explicitly
out of this research-only task's scope to enact.
