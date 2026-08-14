# Bar Buffer Persistence (`talonx_quant`)

Reference doc for how `talonx_quant`'s two in-memory rolling bar buffers are
checkpointed to and reloaded from `quant.db`, and specifically how each one
handles a restart gap (a quick redeploy, an overnight shutdown, a weekend
shutdown). Written up after a live incident where confluence-gate suppression
and a stalled `yfinance` feed were being investigated and the warm-up cost of
routine restarts came up as a related, separate question.

Code involved:
- `talonx_quant/buffer.py` — `RollingBarBuffer`
- `talonx_quant/consumer.py` — `QuantScanner._checkpoint_loop`,
  `_checkpoint_all_buffers`, `_load_buffers_from_store`
- `talonx_quant/store.py` — `QuantStateStore.checkpoint_buffer`,
  `load_buffer`, `buffered_symbols` (table: `bar_buffer`)
- `talonx_quant/config.py` — `buffer_checkpoint_interval_seconds`,
  `buffer_reload_max_gap_seconds`
- `scripts/ticker_funnel_report.py` — section "2b. BUFFER WARM-UP" reads
  this same table to show live warm-up progress per ticker

## What a "bar" is in this system

Market data comes from `yfinance` polling (`TALONX_YF_POLL_INTERVAL`, `.env`
value `12` in this deployment — every 12 seconds). Each poll cycle stamps
all tracked symbols with one shared `now = datetime.now(utc)` timestamp.
`RollingBarBuffer.add_bar()` only appends a new entry if that timestamp
differs from the symbol's last buffered entry, so in practice **every poll
cycle produces a new "bar"** — these are 12-second live-price snapshots
being treated as bars, not calendar-aligned 1-minute candles.

## Two independent buffers, fed from the same stream

| | 1-min buffer (`self.buffer`) | 15-min HTF buffer (`self.buffer_htf`) |
|---|---|---|
| Capacity | 200 bars/symbol (`max_bars_per_symbol`) | 210 bars/symbol (`htf_max_bars`) |
| Built how | Direct — one live snapshot in, one bar in | Aggregated — `_update_htf_buffer()` rolls incoming snapshots into a running OHLCV accumulator, finalized into a real bar only when wall-clock crosses a 15-min boundary |
| Feeds | RSI, MACD, MA-cross, ATR, confluence scoring | Only the 200-period SMA for the trend gate |
| Warm-up threshold | `min_bars_required = 120` | `htf_sma_period = 200` |
| Time to fill from empty | 120 × 12s ≈ **24 minutes** | 200 × 15min = **~50 continuous hours** |

## Write side: periodic checkpoint

Every `buffer_checkpoint_interval_seconds` (default 60s), `_checkpoint_loop()`
calls `_checkpoint_all_buffers()`, which for every symbol currently known to
either buffer pulls the raw bar list via `buffer.get_bars(symbol)` and writes
it to `quant.db`'s `bar_buffer` table through `checkpoint_buffer()`.

This is a **full delete-then-reinsert** for that `(symbol, buffer_type)` pair
each time, not an incremental append — so the persisted table always mirrors
exactly what's in the live deque at checkpoint time, and never accumulates
rows the live buffer has already evicted.

One additional checkpoint runs on a *graceful* `stop()` (in
`_connect_and_listen`'s `finally` block), so a clean shutdown never loses
anything mid-interval.

**Residual gap**: an abrupt kill (crash, force-kill, power loss — not a clean
`stop()`) between two periodic checkpoints can lose up to
`buffer_checkpoint_interval_seconds` (60s default) of the very latest bars.
Everything older survives.

## Read side: reload on startup, and why the two buffers are gated differently

`_load_buffers_from_store()` runs once, at the very start of `run()`, before
the connect/retry loop begins.

**1-min buffer — gap-gated (`buffer_reload_max_gap_seconds`, default 900s /
15 minutes).** For each symbol, the newest checkpointed bar's timestamp is
compared to `now`. If the gap exceeds the limit, that symbol's entire
checkpoint is discarded and the buffer starts empty (same ~24min re-warm-up
as if persistence didn't exist). Only within the 15-minute window does it
reload.

**15-min HTF buffer — unconditional, no gap check.** Whatever was last
checkpointed reloads regardless of age — 10 hours old, 3 days old, doesn't
matter.

### Why the asymmetry is deliberate

The 1-min buffer feeds crossover logic that explicitly compares **previous
bar vs. current bar** (`macd_prev` vs `macd`, `rsi_prev` vs `rsi`, and the
ATR-move-confirmation gate's `bar_true_range`). Reloading a stale bar as
"previous" would make the first live bar after restart look, to that code,
like a real move happened in one 12-second tick — when it's actually the
accumulated gap since shutdown. Concretely, this would risk:

- `bar_true_range` spiking to roughly the whole gap size, trivially clearing
  `atr_move_multiplier × ATR` — the exact "is this a real move" gate this
  project's analyst-review changes added, defeated by the largest non-real
  move possible.
- That one inflated true-range value feeding into the 14-period ATR average
  for several bars afterward, distorting ATR-based stop/target distances and
  the R:R gate.
- RSI/MACD (both smoothed indicators) baking in one artificial outlier tick,
  risking a spurious crossover/extreme-zone signal that's really just the
  gap, not a genuine intraday move.

The 15-min HTF buffer carries none of this risk: it's never used for
"did something just cross," only as a flat 200-bar average checked once
(`price > htf_sma_200`). One bar in 200 spanning a time gap barely moves the
average (0.5% weight) — the same way any daily/weekly chart already treats a
Friday-close-to-Monday-open gap. And since the entire point of persisting
this buffer is that 50 continuous hours can never be accumulated under a
daily-restart routine, gap-gating it the same way as the 1-min buffer would
make the fix pointless — it has to survive exactly these gaps, or it
accomplishes nothing.

## Restart scenarios

**Restart after ~10 hours (normal end-of-day → next-morning shutdown):**
- 1-min buffer: 10h ≫ 15min limit → discarded → fresh ~24min warm-up.
- 15-min buffer: reloaded as-is. E.g. 40 bars (~10 trading hours) before
  shutdown come back instantly; 160 more (~40 more hours of future uptime,
  spread across however many future days) are still needed to reach 200 and
  activate the trend gate.

**Restart after a weekend (~60+ hour gap):**
- 1-min buffer: same outcome — discarded, ~24min warm-up Monday morning.
  The 15-minute cutoff doesn't scale with gap size; anything past it is
  treated identically whether it's 20 minutes or 3 days.
- 15-min buffer: still reloaded unconditionally — Friday's accumulated bars
  carry straight into Monday, gap included, no special handling needed.

**New ticker added to the watchlist (no prior checkpoint):** both buffers
just start empty, identical to how every ticker behaved before this feature
existed.

## Checking warm-up progress

`scripts/ticker_funnel_report.py <TICKER>` reads `bar_buffer` directly and
prints both buffers' current bar count against their threshold, plus the
oldest/newest checkpointed bar timestamp:

```
python scripts/ticker_funnel_report.py DELL
```

```
-- 2b. BUFFER WARM-UP (bar_buffer checkpoint) ------------------
   1m buffer: 6/120 bars -- warming up (5%) -- unlocks regular signal evaluation
       oldest checkpointed bar: 2026-08-14T13:59:32.075398+00:00
       newest checkpointed bar: 2026-08-14T14:01:21.887075+00:00
  15m buffer: 1/200 bars -- warming up (0%) -- unlocks 15m-200-SMA trend gate
       oldest checkpointed bar: 2026-08-14T13:45:00+00:00
       newest checkpointed bar: 2026-08-14T13:45:00+00:00
```

This read lags the true in-memory buffer by up to
`buffer_checkpoint_interval_seconds` on a live process (it's reading the last
checkpoint, not the live deque) — which is also exactly what would actually
survive a restart at that moment, so it's the right number to look at when
reasoning about warm-up state.

## Related config (all in `talonx_quant/config.py`, env-overridable)

| Setting | Env var | Default | Governs |
|---|---|---|---|
| `buffer_checkpoint_interval_seconds` | `TALONX_QUANT_BUFFER_CHECKPOINT_SECONDS` | 60.0 | How often both buffers are snapshotted to `quant.db` |
| `buffer_reload_max_gap_seconds` | `TALONX_QUANT_BUFFER_RELOAD_MAX_GAP_SECONDS` | 900.0 | 1-min buffer only — max age of the newest checkpointed bar before that symbol's reload is skipped |
| `min_bars_required` | `TALONX_QUANT_MIN_BARS` | 120 | 1-min buffer bars needed before indicators are computed at all |
| `htf_sma_period` | `TALONX_QUANT_HTF_SMA_PERIOD` | 200 | 15-min buffer bars needed before the trend gate has a value to check against |
