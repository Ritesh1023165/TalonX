# Task 118 Part 3 — Original intraday selectivity (read-only inspection, 2026-09-11)

Read-only inspection of the live release worktree's `talonx_quant`/`quant.db`
state. **No production code changed, no threshold lowered, no intraday
production fix applied** — per the task's working boundaries.

## Why configured tickers rarely produce actionable Original alerts

`quant.db.suppression_counts` records every gate rejection by reason, date,
and ticker — this is the authoritative funnel, not an inference. Daily
totals for the last 5 trading days with data:

| date | LOW_VOLATILITY | LOW_CONFLUENCE | OPENING_BLACKOUT | TREND_GATE | other | tickers hit by LOW_VOLATILITY | total |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-10 | 14,973 | 18 | 10 | 1 | 0 | 43/43 | 15,002 (99.81% LOW_VOLATILITY) |
| 2026-09-09 | 14,832 | 8 | 6 | 0 | 0 | 43/43 | 14,846 (99.91%) |
| 2026-09-08 | 12,903 | 0 | 0 | 0 | 5 (`US_MARKET_SESSION_CLOSED`) | 43/43 | 12,908 (99.96%) |
| 2026-09-05 | 17,860 | 0 | 0 | 0 | 5 (`UK_SESSION_CLOSED`) | 43/43 | 17,865 (99.97%) |
| 2026-09-04 | 16,214 | 3 | 0 | 0 | 0 | 43/43 | 16,217 (99.98%) |

**The volatility gate is, overwhelmingly, the single binding constraint** —
on every one of the last 5 sessions it accounts for ≥99.8% of all gate
rejections, hits all 43 configured/selected tickers every day, and dwarfs
every other gate combined by 2–3 orders of magnitude. This is a re-
measurement, not a new finding: it directly **confirms and sharpens** Task
93/94's prior conclusion ("vol gate rejects 92.8%") at materially finer
resolution (now 99.8–99.98% across 5 fresh sessions, ~76,838 total gate
events), consistent with the intervening tasks (95A–95K) that repeatedly
found no exploitable intraday edge once realistic volatility/selectivity
gates are applied.

### Unit trace — confirmed correct, not a bug

`talonx_quant/consumer.py::_fails_min_volatility` (lines 287–298):
`atr_pct = (snapshot.atr / snapshot.price) * 100` (ATR-14 in price-dollars,
divided by price, multiplied by 100 → **percent**), compared directly
against `config.min_atr_pct` (`talonx_quant/config.py:355`,
`TALONX_QUANT_MIN_ATR_PCT`, default **0.25**, also in percent). **Units are
consistent on both sides of the comparison — no unit-mismatch bug.** The
dispatch between this gate and the experimental multi-timeframe regime gate
is centralized in one authoritative function
(`_evaluate_active_volatility_gate`, `consumer.py:301–338`, Task 45),
documented as fails-closed on any unrecognised mode. This is an
**intentionally selective rule**, unchanged and working as designed since
Task 45/93 — not an implementation defect.

### Gate stage separation (from `suppression_counts` reason taxonomy)

The suppression taxonomy itself only records: `LOW_VOLATILITY`,
`LOW_CONFLUENCE`, `OPENING_BLACKOUT`, `CLOSING_BLACKOUT`, `TREND_GATE`,
`LOW_RISK_REWARD`, `US_MARKET_SESSION_CLOSED`, `UK_SESSION_CLOSED`,
`COOLDOWN`, `THROTTLE`, `FUNDAMENTAL_COOLDOWN`, `LOSS_LOCKOUT` — **no
distinct "insufficient warm-up bars" reason exists in this table.** A bar
that has not yet accumulated `min_bars_required` (120, 1-minute) is not
counted as a suppression at all — indicator computation for that
symbol/bar is simply skipped upstream (`talonx_quant/indicators.py:104`,
`if len(df) < config.min_bars_required: return`), so its contribution to
"rarely produces alerts" cannot be separated from the volatility-gate
figures above using this table alone. **This is an evidence gap, not a
claim of zero effect** — see the live warm-up measurement below, which
addresses it directly for today's pre-open state.

Sequence, as implemented: (1) warm-up (`min_bars_required`/`htf_sma_period`
— not evaluated at all if unmet) → (2) volatility gate (`min_atr_pct`, the
dominant filter, §above) → (3) confluence/RR/trend/session gates
(`LOW_CONFLUENCE`/`LOW_RISK_REWARD`/`TREND_GATE`/`OPENING_BLACKOUT`/
`CLOSING_BLACKOUT`/session-closed) → (4) qualified publication
(`dispatch_audit.db alerts`, currently 0 today — `ZERO_ACTIVITY_BY_DESIGN`,
downstream of 0 Quant publications, per the live dashboard's own
`quant_signals` domain note) → (5) delivery/paper execution. Each stage is a
distinct evaluation on a distinct bar; repeated processing of the same bar
by different indicator checks is not counted as independent opportunities
in the totals above (each `suppression_counts` row is one ticker × one
reason × one day, aggregated from per-bar events, not a raw bar count).

## The reported 4/43 intraday warmup readiness — reproduced live, today

Measured directly against the live `quant.db.bar_buffer` at 2026-09-11
10:14 UTC (regular session opens 13:30 UTC — **this is a genuine pre-open
measurement, not mid-session**):

- `min_bars_required = 120` (1-minute buffer), `htf_sma_period = 200`
  (15-minute buffer) — `talonx_quant/config.py:176,385`.
- **15-minute buffer: 43/43 symbols already at 200 bars** (the buffer cap),
  spanning 2026-08-31→2026-09-10 — fully warm, not the readiness gap.
- **1-minute buffer: exactly 4/43 symbols at ≥120 bars** — ADC, AFL, BLK,
  NUE, each carrying **200 bars** (the cap) with timestamps running through
  **2026-09-10T20:30:00 UTC** (yesterday's session, continuous). The other
  **39/43 symbols' 1-minute buffers restart from empty at ~2026-09-11
  04:00 America/New_York (08:00 UTC) today**, with only **23–37 bars**
  accumulated by 06:09 ET (≈2h09m of live accumulation) — well short of 120.

This reproduces the reported "4/43" figure exactly, live.

**Was this expected before open?** No — by design, `talonx_quant.preseed_ordering`
(`run_initial_preseed`, awaited before any live task starts,
`talonx_quant/preseed_ordering.py:1–28`) exists specifically to backfill
`min_bars_required` 1-minute bars via network I/O (yfinance) for **every**
configured symbol before the scanner starts, precisely so this gap does not
happen. Its own docstring states it "never synthesizes" and reports
per-symbol readiness, falling back to live accumulation only for symbols
where the network backfill did not succeed.

**What this pattern (4/43 preseed-succeeded, 39/43 preseed-failed-or-skipped,
reset at process start) is most consistent with**: either (a) the 39
symbols' network backfill failed or was skipped at this morning's process
start while 4 symbols' succeeded, or (b) only 4 symbols retained continuous
buffer state across a process restart (their buffers were simply never
cleared) while the other 39 were rebuilt from empty. **No persisted preseed
status report exists on disk** (`InitialPreseedReport` — grep across
`~/.talonx` found nothing) and this morning's process log was not
retrospectively available within this bounded, read-only session, so the
root cause between (a) and (b) **cannot be distinguished from currently
available evidence** — this is reported as a precise, named gap, not
resolved by inference.

**Was readiness achieved during the regular session (yesterday, 2026-09-10,
as the best available same-symptom precedent)?** The 1-minute buffer's own
retained history shows ADC/AFL/BLK/NUE reaching the 200-bar cap by
2026-09-10T20:30 UTC (just after the 20:00 UTC close) — consistent with
having been warm all session. Whether the *other* 39 symbols were warm
*during* 2026-09-10's regular session cannot be determined from today's
buffer alone (it was overwritten/reset since), and `suppression_counts`
has no warm-up-specific reason code (above) — so this specific question
("did a readiness defect actually cost qualified evaluations, on a day
that has already happened") **remains an evidence gap**, not resolved
here. What can be said with certainty: as of the time of this inspection,
39 of 43 symbols are running the process's live-accumulation fallback
rather than a network-backfilled 120-bar 1-minute buffer, several hours
before today's open — if the accumulation rate observed this morning
(roughly 1 bar per ~3.3 real minutes, 23–37 bars over ~129 minutes) held
constant, reaching 120 bars would take materially longer than the
~3h20m remaining before the 13:30 UTC open, which would put a real,
economically relevant delay into the first part of today's regular
session for those 39 symbols specifically — **this is a forward-looking
risk flagged for operator attention, not verified after the fact, and no
intraday production fix was applied** per this task's boundaries.

## Outcome measurement for the complete predefined candidate population

**Not run.** The task calls for measuring "outcomes for the complete
predefined candidate population, with causal entry timing, direction,
costs and a stated exit horizon" only "where historical data supports it,"
and explicitly requires "one bounded hypothesis before running it" if a
counterfactual (e.g., a relaxed-threshold) analysis is undertaken.
`quant.db.suppression_counts` records *rejections*, not the full underlying
candidate-bar population with realized forward prices — reconstructing that
population causally (every bar that reached the volatility check, its
direction, and its actual forward return at a stated horizon) is a
non-trivial data-engineering task in its own right, already explicitly
performed once at much larger scale in Task 94 (49 studies) and Task 95A
(2020–26, 25.8M SIP bars, `INTRADAY_ALPHA_NOT_SUPPORTED_ACROSS_EXPANDED_REGIMES`
— binding wall = intraday drift ~5bps ≈ round-trip cost). Given that prior,
already-closed result covers exactly this question at far higher power than
anything constructible from `suppression_counts` alone tonight, and no new
justified hypothesis for revisiting it was specified, **this measurement is
not repeated here** — re-running it would be exploratory re-litigation of a
closed space, not a new bounded hypothesis test, and is explicitly out of
scope for this bounded session. This is a stated limitation, not a silent
omission: if the operator wants this rerun, it needs its own explicitly
bounded hypothesis first (per the task's own instruction), which was not
supplied.

## Evidence

Live `quant.db` (`suppression_counts`, `bar_buffer`) queried read-only via
`file:...?mode=ro` SQLite URIs, no writes. `talonx_quant/consumer.py:287-338`,
`talonx_quant/config.py:176,355,385`, `talonx_quant/indicators.py:104`,
`talonx_quant/preseed_ordering.py:1-28` (release worktree, read-only). No
code change made anywhere in the release worktree during this inspection.
