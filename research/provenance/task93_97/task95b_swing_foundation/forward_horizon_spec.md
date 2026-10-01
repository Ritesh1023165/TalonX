# TASK 95B — Phase 2 — Forward Horizon Specification

**Pre-registered before any profitability inspection.** Frozen once written.

All entries are **long-only** and priced on the **split-adjusted regular-session close** (`adj_close`)
unless noted. All horizons count **trading days present in the dataset**, never calendar days.

## Bridge horizons (transitional — NOT a reopening of 5–30-minute mining)

| Horizon | Entry | Exit | Notes |
|---|---|---|---|
| `+60m` | 10:00 ET close (last 1-min ≤ 10:00, must print 09:58–10:05) | 11:00 ET close, same session | intraday only; if session ends first → NaN |
| `+120m` | 10:00 ET | 12:00 ET, same session | |
| `+240m` | 10:00 ET | 14:00 ET, same session | |

Used only in the Phase 3 cost-to-move scan to confirm the intraday cost wall; **not** carried into
Phases 5–17.

## Swing horizons (primary)

| Horizon | Entry timestamp | Exit timestamp | Overnight | Missing-day handling | Holiday handling |
|---|---|---|---|---|---|
| `overnight` | `adj_close(t)` (16:00 ET day *t*) | `adj_open(t+1)` (09:30 ET next trading day) | the whole horizon **is** the overnight | if `t+1` absent (halt) → next available trading day's open, flagged | holidays are simply not trading days; the "next trading day" is used |
| `1d` | `adj_close(t)` | `adj_close(t+1)` | held through 1 overnight | `t+1` = next row in the symbol's series | same |
| `2d` | `adj_close(t)` | `adj_close(t+2)` | 2 overnights | `t+2` = 2 rows forward | same |
| `3d` | `adj_close(t)` | `adj_close(t+3)` | 3 overnights | 3 rows forward | same |
| `5d` | `adj_close(t)` | `adj_close(t+5)` | held ~1 calendar week | 5 rows forward | same |
| `10d` | `adj_close(t)` | `adj_close(t+10)` | ~2 calendar weeks | 10 rows forward | optional / reported where sample allows |

Because the exit is *k rows forward in the symbol's own trading-day series*, holidays and halted
days are automatically skipped — a "5-day" hold spanning a Thanksgiving week is 5 trading days
(~7 calendar days). This is the standard swing convention and keeps every symbol's horizon
comparable in trading-day terms.

**Split ex-date rule:** any forward return whose `[t, t+k]` window contains a split ex-date is set
to NaN (see `aggregation_spec.md`). ~0.1 %–0.9 % of rows per horizon.

**Delisted / unavailable:** none in the universe; a symbol simply has no rows past its last trading
day (25 names end 2025-08-14). Forward returns that would need a row past the series end are NaN
(counts: 47 for 1d … 470 for 10d).

**Intra-path low:** `fwd_{k}d_minlow` = worst `adj_low` over `(t, t+k]` relative to `adj_close(t)` —
retained for MAE / stop modelling in later phases, not part of the entry/exit definition.

## Overlap

Consecutive daily rows produce **heavily overlapping** k-day forward returns (a 5-day return shares
4 of 5 days with the next). This is handled statistically in **Phase 12** (non-overlapping subsampling
+ block bootstrap + symbol-clustered CIs). Naïve i.i.d. treatment of overlapping returns is not used
for any confidence claim.
