# Task 118A Priority 2 — Original warmup / data readiness (2026-09-11)

**Verdict: expected/external-provider degradation, not a TalonX implementation
defect. No production fix applied — none is warranted by the evidence found.**
Read-only investigation only, per this task's boundary ("no intraday production
fixes... do not lower thresholds... do not manufacture bars... bounded
requests only").

> **2026-09-11 (Task 118G) correction, original text below unedited**:
> the *provider* failure was correctly found transient, and no
> provider-side code defect existed — that conclusion stands. However, a
> separate, real **application-side** defect was later found (Task 118F,
> not this task): `QuantScanner._preseed_1m_if_needed`'s "attempted"
> marker was set unconditionally on the first attempt, regardless of
> success or failure, silently preventing any retry for the rest of the
> process's life — this is why natural live-tick accumulation was left as
> the *only* recovery path, and why it took hours for the slowest
> symbols. Task 118F root-caused, fixed, tested, and deployed a bounded
> recovery sweep for exactly this gap — see
> `docs/audits/task118f_resilient_warmup/`.

## What was traced

- `min_bars_required = 120` (1-minute buffer), `htf_sma_period = 200`
  (15-minute buffer) — `talonx_quant/config.py:176,385`.
- `talonx_quant.preseed_ordering.run_initial_preseed()` — awaited in
  `run_talonx.py` BEFORE any live task starts (line ~1188), backfills
  `min_bars_required` 1-minute bars via yfinance for every configured
  symbol, reports per-symbol readiness, and — critically — **never blocks
  or raises**: a symbol that fails to hydrate simply runs normally
  afterward via `QuantScanner`'s own live-accumulation fallback (the
  module's own docstring, `preseed_ordering.py:22-27`).
- Persisted evidence: `results/task100b_runtime_integration/_supervisor_logs/original.log`
  (the real, continuously-appended stdout of the `original` supervised
  component — the actual `run_talonx.py` process backing today's live
  session) carries every morning's preseed summary line, going back to
  2026-09-08.

## What the log actually shows (not inferred — read directly)

| date/time (UTC) | preseed result |
|---|---|
| 2026-09-08 08:09 | **43/43 ready** |
| 2026-09-08 09:44 (a later same-day restart) | **0/43 ready — ZERO READY** |
| 2026-09-09 07:57 | **43/43 ready** |
| 2026-09-10 08:44 | **43/43 ready** |
| **2026-09-11 09:12 (today's activation startup)** | **0/43 ready — ZERO READY** |

Today's preseed genuinely **failed completely** — not "4/43" as a live
inspection of `quant.db.bar_buffer` alone (without this log) suggested
earlier today. That "4/43" figure (ADC, AFL, BLK, NUE showing 200
carried-over 1-minute bars while the other 39 showed only newly-
accumulated bars) is explained by those 4 symbols' buffer rows not yet
having aged out from a **prior successful day**, not by a partial preseed
success today — today's own preseed attempt produced zero readiness for
every symbol, confirmed by the log line itself.

## Root cause: found, and it is external

The 09:12:04–09:12:35 UTC window of today's log is saturated with:
```
[ERROR] yfinance: $AAPL: possibly delisted; no price data found  (period=1d)
[ERROR] yfinance: $ABT: possibly delisted; no price data found  (period=1d)
[ERROR] yfinance: $JPM: possibly delisted; no price data found  (period=1d)
... (25 of the 43 symbols hit within this one ~20-second window, including
    obviously-not-delisted mega-caps: AAPL, MSFT-adjacent GOOGL, JPM, TSLA)
[ERROR] yfinance:
6 Failed downloads:
['PG', 'AFL', 'BLK', 'ABT', 'ADC', 'NUE']: possibly delisted; no price data
found  (period=1d)
```
`yfinance`'s "possibly delisted; no price data found" is Yahoo Finance's
own error string for a `period="1d"` request that returned no usable data
— this is a well-known **transient upstream (Yahoo-side) failure mode**,
not a TalonX bug: it fires for real, actively-traded large-cap tickers
(AAPL, JPM, GOOGL, TSLA all appear in the error list this morning), which
rules out an actual delisting or a TalonX-side symbol-mapping error. The
pattern across 4 mornings (3 clean 43/43 successes, 2 complete 0/43
failures — one on 09-08's second startup, one today) is consistent with an
**intermittent external provider issue**, not a persistent code defect:
if this were a TalonX logic bug, it would fail identically every run, not
3-successes-then-1-failure.

## Was the fallback expected, and did it work?

Yes to both, evidenced directly:
- `preseed_ordering.py`'s own docstring documents this exact scenario
  ("Fail-closed per symbol, never synthesized... it still runs normally
  afterward via QuantScanner's own existing live-accumulation
  fallback... This module never raises or blocks the caller").
- Live inspection of `quant.db.bar_buffer` (2026-09-11 10:14 UTC, ~3h20m
  pre-open) confirmed the fallback IS actively running: the 39 symbols
  without carried-over bars each showed a **live, growing** bar count
  starting fresh at ~04:00 America/New_York today (23–37 bars accumulated
  by the inspection time), exactly the "existing live-accumulation
  fallback" the docstring describes, not a stalled or dead buffer.

## Was regular-session evaluation prevented?

**Not determined, and this is explicitly left open, not resolved by
inference.** As of this investigation (pre-open, ~3h20m before the 13:30
UTC open), the 39 lagging symbols have not yet reached 120 bars via live
accumulation. Whether they cross that threshold before or shortly after
today's regular open — and therefore whether any of today's early-session
bars for those symbols go unevaluated by the volatility gate — requires
observing the actual regular session, which had not yet occurred at the
time of this investigation. **If regular-session observation is still
required, this states it plainly: it is.** No claim of "readiness passed"
is made from this pre-open, fixture-free inspection alone.

## Was this a unit/implementation error, or an intentionally selective threshold?

Neither, for the warm-up gap itself — it is not a threshold at all, it is
a **data-availability** gap upstream of the (separately verified,
correctly-implemented, see `docs/research/TASK118_ORIGINAL_SELECTIVITY.md`)
volatility gate. `min_bars_required=120` is an intentional, documented
design choice (unchanged), not touched here.

## Decision: no code change

Given (a) the failure is attributable to an external provider's transient
error, evidenced directly in the process's own log, not a logic defect in
TalonX's preseed/fallback code, and (b) the designed fallback mechanism is
confirmed actively working as intended — **no fix was applied.** Per this
task's explicit instruction ("If behavior is expected, document it"), this
document is that record. No threshold was lowered, no bar count was
reduced, no bars were manufactured, and no new network request was made
against the live feed to "test" this further (the evidence above is
entirely from already-persisted logs and already-populated `quant.db`
state, read-only).

## One presentation question checked, and NOT found to be misleading

The live dashboard's `usable_coverage: 1.0` / `symbols_priced: 51` field
(`talonx_ops/market_health.py`, `coverage_ratio`) was checked against this
finding for a possible "readiness presented as green when it isn't" bug.
Traced to source: this field counts `latest_prices` rows (does a symbol
have *any* known current price at all) — a genuinely different, correctly
-labelled measurement from 1-minute-buffer warm-up readiness for the
volatility gate. It is not observed to claim more than it measures
anywhere in the dashboard code inspected. No change made here; flagging a
presentation defect without a concrete false claim to cite would itself be
inventing an issue, which this task instructs against.
