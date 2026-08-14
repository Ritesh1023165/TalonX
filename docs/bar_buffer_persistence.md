# Bar Buffer Architecture, Historical Pre-Seeding & Session-Aware Buffering (`talonx_quant`)

Reference doc for how `talonx_quant` builds, checkpoints, reloads, and
instantly warms up its two in-memory rolling bar buffers. Originally written
after a live incident investigating confluence-gate suppression and a
stalled `yfinance` feed; rewritten after a deeper review found the buffers
were mathematically distorted, not just slow to warm up (see "History"
below).

Code involved:
- `talonx_quant/buffer.py` — `RollingBarBuffer` (session-tagged bars)
- `talonx_quant/session.py` — `get_session` (pre_market/regular/closed)
- `talonx_quant/preseed.py` — `fetch_1m_history`/`fetch_15m_history`
  (yfinance historical backfill, fails soft)
- `talonx_quant/consumer.py` — `QuantScanner._update_1m_buffer`,
  `_update_htf_buffer`, `_checkpoint_loop`, `_checkpoint_all_buffers`,
  `_load_buffers_from_store`, `_preseed_1m_if_needed`,
  `_preseed_htf_if_needed`, `preseed_symbols`
- `talonx_quant/indicators.py` — `_same_session_tail` (session-aware ATR reset)
- `talonx_quant/store.py` — `QuantStateStore.checkpoint_buffer`,
  `load_buffer`, `buffered_symbols` (table: `bar_buffer`, now with a
  `session` column)
- `talonx_quant/config.py` — pre-seed/RTH/gap-reload settings
- `run_talonx.py` — `WatchlistDrivenQuantPreseed` (drives pre-seeding from
  the live watchlist; `QuantScanner` itself never imports `talonx_watchlist`)
- `scripts/ticker_funnel_report.py` — section "2b. BUFFER WARM-UP" reads
  the `bar_buffer` checkpoint to show live warm-up progress per ticker

## History: from raw poll snapshots to calendar-aligned candles

Market data arrives from `yfinance` polling (`TALONX_YF_POLL_INTERVAL`,
e.g. every 12 seconds) as a live LAST-PRICE snapshot per symbol, stamped
`now = datetime.now(utc)` each cycle — not a discrete "new 1-minute bar
closed" push. Originally, each poll's snapshot was appended to the 1-min
buffer directly, using the event's own timestamp. Since every poll produces
a distinct timestamp, **every poll cycle produced a new "bar"** — 14-period
RSI/MACD were tracking 14 x 12s = 2.8 minutes of price noise, not 14 actual
calendar minutes. New tickers also took ~24 minutes (120 bars x 12s) to
clear `min_bars_required`, and the 15-min HTF buffer took ~50 continuous
hours (200 bars) to warm up the trend gate — an 8-trading-day cold start
for a freshly added ticker.

This has been fixed with three changes, described below: **true
calendar-aligned 1-minute aggregation**, **instant historical pre-seeding**,
and **session-aware buffering**.

## What a "bar" is now

`QuantScanner._update_1m_buffer` floor-buckets each incoming poll snapshot
to the minute and builds a real OHLCV candle purely from the tick's own
price (`event.close`) — **not** the event's `open`/`high`/`low` fields,
which for the yfinance polling fallback are the whole DAY's open/high/low
(constant all session, useless for a single minute's shape):

- **Open** = the first tick's price this minute.
- **High**/**Low** = running max/min of every tick's price this minute.
- **Close** = the latest tick's price.
- **Volume** = accumulated across every tick this minute.

The still-forming bucket is written into `self.buffer` on **every** tick
(so indicator computation always sees the latest partial minute's evolving
price immediately) — but it updates the SAME row in place
(`RollingBarBuffer.add_bar`'s same-timestamp-replace behavior) until the
wall clock actually crosses into a new minute, at which point a genuinely
new row is appended. `min_bars_required` bars now really do span that many
calendar minutes, not raw poll cycles.

The 15-min HTF buffer (`_update_htf_buffer`) works the same way it always
has: it finalizes the PREVIOUS 15-minute bucket into `buffer_htf` only once
a tick from the NEXT bucket arrives — the currently-forming HTF candle is
never pushed early/partial (unlike the 1-min buffer, which needs to show
its partial candle immediately for live signal evaluation; the HTF buffer
only ever feeds a flat 200-bar SMA, so there's no such urgency).

## Session-aware buffering

Every bar (from live aggregation, checkpoint reload, OR historical
pre-seeding) is tagged with its US-equities session via `session.py`:
`pre_market` (04:00–09:30 ET), `regular` (09:30–16:00 ET), or `closed`.
`RollingBarBuffer.add_bar` auto-derives this from the bar's timestamp if
the caller doesn't pass one explicitly.

**15-min HTF buffer is Regular-Trading-Hours-only** (`rth_only_htf_sma`,
default on): `_update_htf_buffer` simply never finalizes a bucket that
falls outside regular hours into `buffer_htf`. The 200-SMA trend gate this
buffer exists for is RTH-only by definition, so a pre-market 15-min candle
would only occupy an `htf_max_bars` slot the gate can never use.

**1-min buffer's ATR baseline resets at the regular-session open**:
`indicators.py`'s `compute_indicators` recomputes ATR/`bar_true_range` from
scratch on every call (there's no persistent running state to explicitly
"reset"), so `_same_session_tail` restricts their INPUT to the trailing
contiguous run of bars sharing the LATEST bar's session tag. The instant
the regular session opens, pre-market bars fall out of that window on
their own — ATR/`bar_true_range` go back to `None` (a fresh warm-up) until
enough regular-session bars accumulate, rather than blending the thin
pre-market range into the post-open baseline. RSI/MACD/SMA are NOT
restricted this way — only the ATR-based movement-confirmation/
risk-reward inputs get the reset.

**Pre-market vs. regular thresholds**: unchanged from before this
rewrite — `strategy.py`'s `_pick_volume_threshold` already applies a
stricter volume-surge ratio pre-market, and the pre-market liquidity/
news-catalyst gates in `consumer.py` are unaffected by any of the above.

## Instant historical pre-seeding

`QuantScanner` backfills both buffers via `yfinance.Ticker(...).history()`
(`preseed.py`) the moment a symbol is seen with too little history, instead
of waiting for live ticks to accumulate:

| | 1-min buffer | 15-min HTF buffer |
|---|---|---|
| Triggered when | `buffer.bar_count(symbol) < min_bars_required` | `buffer_htf.bar_count(symbol) < htf_sma_period` (or a forced backfill, see below) |
| yfinance call | `history(period=preseed_1m_period, interval="1m")` (default period `1d`) | `history(period=preseed_15m_period, interval="15m")` (default period `1mo`) |
| Session filter | none | filtered to `session == "regular"` bars only when `rth_only_htf_sma` is on |
| Bars kept | the most recent `min_bars_required` (default 120) | the most recent `htf_sma_period` (default 200) |
| Checkpointed | immediately (`store.checkpoint_buffer`), not waiting for the 60s periodic loop | same |

Attempted **at most once per symbol per process lifetime** (tracked in
`_preseeded_1m`/`_preseeded_htf`) — a failed/rate-limited attempt falls
back to normal live accumulation rather than retrying every tick; the
periodic checkpoint/live-fill path remains the eventual safety net, same
"attempt once, don't hammer a failing external API" posture
`run_talonx.py`'s `WatchlistDrivenIngestion` already uses for its own
reactive triggers.

**Disable entirely**: `TALONX_QUANT_PRESEED_ENABLED=false` — every symbol
then re-warms up purely from live ticks/checkpoint reload, same as before
this feature existed.

### Two triggers, one code path

1. **On boot / watchlist reconciliation** — `run_talonx.py`'s
   `WatchlistDrivenQuantPreseed` calls `QuantScanner.preseed_symbols()` once
   for the WHOLE watchlist at startup, then again for just the symbol(s)
   that changed whenever it detects an addition/resume (polled every
   `TALONX_WATCHLIST_POLL_INTERVAL` seconds, same cadence
   `WatchlistDrivenIngestion` uses). `QuantScanner` itself never imports
   `talonx_watchlist` — this class is the one place that bridges the two,
   keeping `talonx_quant` self-contained at the code level.
2. **On checkpoint reload** — `_load_buffers_from_store` (see "Restart
   scenarios" below) falls through to the same pre-seed methods whenever a
   reload leaves a buffer short of its threshold.

Running `talonx_quant.run` standalone (not through `run_talonx.py`) only
gets trigger 2 — there's no watchlist reconciler in that entrypoint, so a
genuinely NEW ticker (no prior checkpoint at all) won't be pre-seeded until
its first live tick arrives and `_load_buffers_from_store` has already run
once at boot. In practice, run through `run_talonx.py` for full coverage.

## Write side: periodic checkpoint

Every `buffer_checkpoint_interval_seconds` (default 60s), `_checkpoint_loop()`
calls `_checkpoint_all_buffers()`, which for every symbol currently known to
either buffer pulls the raw bar list via `buffer.get_bars(symbol)` — now
including each bar's `session` tag — and writes it to `quant.db`'s
`bar_buffer` table through `checkpoint_buffer()`.

This is a **full delete-then-reinsert** for that `(symbol, buffer_type)`
pair each time, not an incremental append — so the persisted table always
mirrors exactly what's in the live deque at checkpoint time.

One additional checkpoint runs on a *graceful* `stop()`, and a successful
pre-seed checkpoints that one symbol IMMEDIATELY rather than waiting for the
periodic loop — so `ticker_funnel_report.py` reflects a freshly pre-seeded
ticker as ready within seconds of it being added, not up to 60s later.

**Residual gap**: an abrupt kill (crash, force-kill, power loss) between two
periodic checkpoints can still lose up to `buffer_checkpoint_interval_seconds`
of the very latest LIVE bars (pre-seeded bars are unaffected once
checkpointed). Everything older survives.

## Read side: reload on startup, and Requirement 4's gap handling

`_load_buffers_from_store()` runs once, at the very start of `run()` (now
`async`, since a stale/short reload can trigger a blocking-off-the-event-loop
yfinance pre-seed call), before the connect/retry loop begins.

**1-min buffer — gap-gated (`buffer_reload_max_gap_seconds`, default 900s /
15 minutes), then pre-seeded if still short.** For each symbol, the newest
checkpointed bar's timestamp is compared to `now`. If the gap exceeds the
limit, that symbol's entire checkpoint is discarded. Either way (discarded,
or reloaded but under `min_bars_required`), `_preseed_1m_if_needed` runs
immediately afterward — so a stale checkpoint falls through to an instant
yfinance backfill instead of a ~24-minute live re-warm-up.

**15-min HTF buffer — unconditional reload, PLUS a backfill if the gap is
large.** Whatever was last checkpointed reloads regardless of age. On top of
that, if the newest checkpointed bar is older than `htf_backfill_gap_seconds`
(default 86400s / 24h — e.g. after a weekend), `_preseed_htf_if_needed` is
called with `force=True`, backfilling via yfinance whatever's missing since
the checkpoint gap, on top of the unconditional reload.

### Why the 1-min buffer is still gap-gated even with pre-seeding available

The 1-min buffer feeds crossover logic that explicitly compares **previous
bar vs. current bar** (`macd_prev` vs `macd`, `rsi_prev` vs `rsi`, and the
ATR-move-confirmation gate's `bar_true_range`). Reloading a stale bar as
"previous" would make the first live bar after restart look like a real move
happened in one tick. Pre-seeding a FRESH set of recent historical bars
(rather than reloading the stale ones) avoids this entirely — the gap gate
and the pre-seed fallback work together, not redundantly.

## Restart scenarios

**Restart after ~10 hours (normal end-of-day → next-morning shutdown):**
- 1-min buffer: gap > 15min limit → checkpoint discarded → immediately
  pre-seeded via yfinance instead of a ~24min live re-warm-up.
- 15-min buffer: reloaded as-is (gap < 24h backfill threshold, no forced
  backfill) — e.g. 40 bars (~10 trading hours) before shutdown come back
  instantly; live accumulation fills in the rest.

**Restart after a weekend (~60+ hour gap):**
- 1-min buffer: same outcome as above — discarded, pre-seeded instantly.
- 15-min buffer: reloaded unconditionally, AND backfilled (gap > 24h) —
  Friday's accumulated bars carry into Monday, and any bars missing over
  the weekend are filled via yfinance rather than left as a gap.

**New ticker added to the watchlist (no prior checkpoint):** both buffers
are pre-seeded via `run_talonx.py`'s `WatchlistDrivenQuantPreseed` within
one watchlist poll interval (default 10s) — see "Two triggers" above.

## Checking warm-up progress

`scripts/ticker_funnel_report.py <TICKER>` reads `bar_buffer` directly and
prints both buffers' current bar count against their threshold, plus the
oldest/newest checkpointed bar timestamp. Immediately after a fresh boot
with pre-seeding enabled, this should show both buffers already at/near
100%:

```
python scripts/ticker_funnel_report.py DELL
```

```
-- 2b. BUFFER WARM-UP (bar_buffer checkpoint) ------------------
   1m buffer: 120/120 bars -- READY (100%) -- unlocks regular signal evaluation
       oldest checkpointed bar: 2026-08-14T13:59:32.075398+00:00
       newest checkpointed bar: 2026-08-14T14:01:21.887075+00:00
  15m buffer: 200/200 bars -- READY (100%) -- unlocks 15m-200-SMA trend gate
       oldest checkpointed bar: 2026-08-14T13:45:00+00:00
       newest checkpointed bar: 2026-08-14T13:45:00+00:00
```

This read lags the true in-memory buffer by up to
`buffer_checkpoint_interval_seconds` on a live process for LIVE bar
updates, but a successful pre-seed checkpoints immediately (see "Write
side" above) — so a freshly pre-seeded ticker shows up as ready right away,
not after waiting for the next periodic checkpoint.

## Related config (all in `talonx_quant/config.py`, env-overridable)

| Setting | Env var | Default | Governs |
|---|---|---|---|
| `buffer_checkpoint_interval_seconds` | `TALONX_QUANT_BUFFER_CHECKPOINT_SECONDS` | 60.0 | How often both buffers are snapshotted to `quant.db` |
| `buffer_reload_max_gap_seconds` | `TALONX_QUANT_BUFFER_RELOAD_MAX_GAP_SECONDS` | 900.0 | 1-min buffer only — max age of the newest checkpointed bar before that symbol's reload is skipped (falling through to pre-seed) |
| `min_bars_required` | `TALONX_QUANT_MIN_BARS` | 120 | 1-min buffer bars needed before indicators are computed at all; also the pre-seed threshold |
| `htf_sma_period` | `TALONX_QUANT_HTF_SMA_PERIOD` | 200 | 15-min buffer bars needed before the trend gate has a value to check against; also the pre-seed threshold |
| `historical_preseed_enabled` | `TALONX_QUANT_PRESEED_ENABLED` | true | Enables/disables startup historical backfilling via yfinance entirely |
| `preseed_1m_period` | `TALONX_QUANT_PRESEED_1M_PERIOD` | `1d` | yfinance lookback period for 1-min buffer pre-seeding |
| `preseed_15m_period` | `TALONX_QUANT_PRESEED_15M_PERIOD` | `1mo` | yfinance lookback period for 15-min HTF buffer pre-seeding |
| `rth_only_htf_sma` | `TALONX_QUANT_RTH_ONLY_HTF` | true | Restricts the 15m-200-SMA trend gate's source buffer to Regular Trading Hours bars only |
| `htf_backfill_gap_seconds` | `TALONX_QUANT_HTF_BACKFILL_GAP_SECONDS` | 86400.0 | Checkpoint-gap threshold (e.g. a weekend) that triggers a forced HTF yfinance backfill on top of the unconditional reload |
