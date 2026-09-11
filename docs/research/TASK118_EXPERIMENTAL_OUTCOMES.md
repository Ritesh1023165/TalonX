# Task 118 Part 4 — Experimental paper outcomes reconciliation (2026-09-11)

Read-only query of `~/.talonx/experimental/exp_alerts.db` (via SQLite
`mode=ro` URIs, no writes) and the live `:8787` `validation` dashboard
section. **No synthetic entries, no forced exits, no live-ledger writes, no
Experimental Telegram enablement** — all 5 positions below have
`sent: 0` in the raw table, confirming the external send boundary held for
every one of them.

## The five open positions

| symbol | side | entry | qty | entry (opened_at, UTC) | stop | target | admitted_by |
|---|---|---:|---:|---|---:|---:|---|
| VRT | BUY | 274.5585 | 9.1055 | 2026-09-09T15:03:34Z | 273.6548 | 296.5033 | volatility+confluence |
| BLSH | BUY | 35.2388 | 70.9445 | 2026-09-09T15:03:34Z | 34.7233 | 36.1233 | volatility+confluence |
| AMD | BUY | 505.4163 | 4.9464 | 2026-09-10T16:51:26Z | 504.5247 | 529.3200 | volatility+confluence |
| STX | BUY | 870.9527 | 2.8704 | 2026-09-10T18:45:38Z | 869.1969 | 907.2250 | volatility+confluence |
| SPCX | BUY | 148.2276 | 16.8660 | 2026-09-10T19:29:46Z | 144.6133 | 152.0633 | volatility+confluence+rr |

All 5 are **currently recorded as still open** (`exit: null`,
`closed_at: null`). **Realized P&L for all 5 = $0.00** — none has closed, so
none has a booked cost (`est_costs`) or realized P&L; there is no exit
obligation recorded because no automatic exit mechanism actually runs (see
next section) and no manual exit was taken.

## Unrealized P&L — timestamped reference prices, gross only

Using the most recent bar price from the live `directional_alerts` feed
(the freshest available timestamped price per symbol; **all timestamps are
2026-09-10 — no new bar exists yet as of this 2026-09-11 10:1x UTC pre-open
inspection**, so every figure below is **stale by design of today's
pre-open timing**, not an error):

| symbol | last price | timestamp (UTC) | unrealized $ (gross, no cost) | unrealized % | vs. stop |
|---|---:|---|---:|---:|---|
| VRT | 247.6500 | 2026-09-10T16:49:29Z | **−$245.02** | −9.80% | **below stop (273.65)** |
| BLSH | 34.0400 | 2026-09-10T19:39:00Z | **−$85.05** | −3.40% | **below stop (34.72)** |
| AMD | 505.2900 | 2026-09-10T16:41:00Z | −$0.62 | −0.02% | above stop |
| STX | 870.0000 | 2026-09-10T19:32:22Z | −$2.73 | −0.11% | above stop |
| SPCX | 148.1905 | 2026-09-10T19:27:00Z | −$0.62 | −0.02% | above stop |

**Total unrealized: −$334.04 (gross, no round-trip cost booked since none
has closed).** These are gross mark-to-reference figures using the last
observed bar; no cost/spread has been applied because these positions
remain open in the store, and `est_costs`/`net_pnl` are only populated by
`close_long()` at actual exit (§below) — reporting a "net" unrealized
figure here would fabricate a cost that has not, per the store's own
model, been incurred. **Unknown/未-priced values were never set to
zero** — every one of the 5 positions had a real, timestamped last price
available; there was no UNKNOWN case to report this cycle.

## Finding: the stop-loss/take-profit/EOD-flatten exit mechanism exists in code but is never invoked by the live process

`talonx_signals/experimental_paper.py:148-170` implements
`ExperimentalPaperEngine.check_exits(symbol, price)` (stop-loss / take-
profit) and `flatten_all(prices)` (EOD flatten) — both fully functional,
tested logic (`close_long(..., exit_reason="stop_loss"|"target_exit"|"eod_flatten")`).
**Neither is called anywhere in `talonx_signals/run.py`, the live
Experimental process's own main loop** — `run.py` only calls
`self.paper.open_long(...)` (line 186); a repository-wide search for call
sites of `check_exits`/`flatten_all` outside test files found **zero**
callers in `talonx_signals/` (the only other real caller,
`talonx_piv/session_runner.py:705`, calls a *different* engine's
`flatten_all` — an unrelated PIV component, not this Experimental engine).

**This is consistent with, and directly explains, the observed data**: VRT
and BLSH's last known reference prices are both **already below their
recorded stop-loss levels** (VRT −9.80% past entry vs. a −0.33% stop
distance; BLSH −3.40% vs. a −1.46% stop distance), yet both remain "open"
with no exit recorded. Absent live invocation, `check_exits` can never fire
regardless of how far price moves past a recorded stop — the 5 open
positions will accumulate indefinitely until a human or a different
process closes them. **This is a genuine, previously-undocumented gap in
the Experimental paper-trading lifecycle**, reported here as a read-only
finding (file:line cited above) — **not fixed**, per this task's working
boundaries ("no synthetic historical entries, forced exits, live ledger
writes" and no production code changes while a session is live).

## Forward-outcome sample reconciliation

Live dashboard `validation.forward_outcomes` (source: `forward_outcomes.db`,
Task 99G live wiring):

| metric | value |
|---|---:|
| total observations | 200 |
| resolved at 30-minute horizon | 200 / 200 (100%) |
| resolved at 60-minute horizon | 200 / 200 (100%) |
| resolved at end-of-day horizon | 200 / 200 (100%) |
| resolved at +1-trading-day horizon | 81 / 200 (40.5%) |
| pending (awaiting the +1D horizon specifically) | 119 / 200 (59.5%) |

The dashboard's single `"pending": 119` figure is **not** "119 unobserved
alerts" — every one of the 200 is fully resolved at 30m/60m/EOD; "pending"
here specifically means `r_1d IS NULL`, i.e. the observation's issuing date
has not yet had its **next** trading session's close pass, matched to the
sample data's own `"status": "PENDING_1D"` rows. This reconciles exactly
(200 total = 81 resolved_1d + 119 pending_1d).

**Direction convention, traced in code**
(`talonx_signals/telemetry.py::_resolve_field`): `r_{horizon}` always
stores the **raw, unsigned price return** (`(price − reference) / reference
× 100`); a *separate* `hit_{horizon}` field captures directional
correctness (`favourable = ret > 0` if `BULLISH`, `ret < 0` if `BEARISH`).
This is correct and deliberate — a BEARISH alert with a negative `r_30m`
(price fell) is a *win* for that call, reflected in `hit_30m`, not in the
sign of `r_30m` itself. Confirmed against a live sample row (BLSH, BEARISH,
`r_30m: −0.426`, price falling — directionally correct).
**Cost assumption**: `forward_outcomes` records are **gross price-return
diagnostics only** — no spread/cost is deducted anywhere in
`ForwardOutcomeRecorder.on_price`. This is distinct from
`experimental_trades`' own `est_costs`/`net_pnl` fields, which *do* apply a
spread at actual entry/exit (`experimental_paper.py`'s `apply_spread`).
Conflating the two would understate real round-trip cost for any
`kind: "trade"` observation; they are reported separately here.

## Housekeeping note

While querying `~/.talonx` databases for this section, an initial mistyped
path (`~/.talonx/exp_alerts.db` instead of the real
`~/.talonx/experimental/exp_alerts.db`) caused `sqlite3.connect()` to
create a new, empty (0-byte) stray file at the wrong path. It is **not**
read by any code path (verified: the real path is
`~/.talonx/experimental/exp_alerts.db`, confirmed by
`talonx_signals/run.py:94`/`dashboard.py:339`) and contains no data or
schema. Deletion was attempted and blocked by this session's own tool
permission classifier; it is reported here rather than removed by another
means. **No production or Experimental data was affected.**

## Evidence

`~/.talonx/experimental/exp_alerts.db` (`experimental_trades`, read-only),
live `:8787` `/api/section/validation` (checked at 2026-09-11T10:12–10:14Z),
`talonx_signals/experimental_paper.py:100-170`, `talonx_signals/run.py`
(grep for `check_exits`/`flatten_all` call sites — none found),
`talonx_signals/telemetry.py:190-330`.
