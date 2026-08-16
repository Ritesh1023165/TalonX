# `talonx_quant` — Module 2: Technical & Quantitative Scanner

```
talonx:market:stream (Redis)
    → parse + validate each message as MarketTickEvent
    → only BAR-type events matter (trades/quotes are ignored --
      indicators need OHLCV, not tick-level data)
    → append to a per-ticker rolling buffer (bounded, oldest bars drop off)
    → once enough history exists (120 bars by default):
        → compute RSI, MACD, SMA fast/slow, volume-surge ratio, ATR(14) via pandas_ta
        → evaluate against configured thresholds, EDGE-TRIGGERED (fires
          only on the bar the condition first becomes true, not every
          subsequent bar it remains true), AND requiring this bar's own
          true range to clear 1.0x ATR (a routine, average-sized bar
          doesn't count as a real move):
            - RSI curls back ABOVE 30 (was below, recovers) AND volume > 2x average → bullish (oversold reversal + surge)
            - RSI crosses over 70 AND volume > 2x average  → bearish (overbought + surge)
            - MACD line crosses its signal line             → bullish/bearish cross
            - fast MA crosses slow MA, spread >= 0.15% of price → golden/death cross
        → every signal that fires carries a DIRECTION-AWARE confluence_score
          (0-3: MACD cross + RSI extreme IN THAT DIRECTION + volume surge --
          an overbought RSI earns a BULLISH candidate 0 points for that leg)
          and a structural risk_reward_ratio (distance to the prior session's
          nearest pivot level / 1.5x ATR)
    → candidate signal(s) for a ticker are DROPPED if that ticker is
      currently in POST-LOSS LOCKOUT (75 min default, armed when
      talonx_paper reports a losing SELL for it) or within its standard
      post-signal cooldown (default 20 min)
    → candidates below confluence_score_min (default 2) or
      min_risk_reward_ratio (default 1.5) are DROPPED next, BEFORE the
      cooldown lock is armed -- a filtered-out candidate must not still
      consume the ticker's cooldown slot
    → surviving candidate(s) arm the ticker's cooldown now and are buffered
    → every 60s (default), the buffer is ranked by (confluence_score,
      volume_surge_ratio) and only the top 3 (default) are published to
      Redis (talonx:signals:quant) -- the rest are dropped
    → EVERY dropped candidate, at EVERY gate above, also publishes a
      RejectedCandidateEvent to talonx:quant:rejected -- talonx_dispatch
      persists one row per candidate to its rejected_candidates table (see
      dispatch.md's Rejection Trace Logging section)
```

**Noise + signal-quality filters (edge-triggering/hysteresis added after
live testing surfaced alert chatter; ATR-move/confluence/risk-reward/
post-loss-lockout added after a later live paper-trading review found a
0.33 profit factor and 25% win rate, with 3 consecutive SMCI losses
driving 93% of session losses — see [performance.md §5](../performance.md#5-talonx_quant-noise-filters-why-and-what-changed)
for the full before/after):**
- **Edge-triggering** (`strategy.py`) — every signal type, including the
  RSI+volume setup, fires only on the transition bar. Previously the
  RSI+volume check was a pure level check that would re-fire on every bar
  RSI stayed under 30/over 70; MACD and MA crossovers were already
  edge-triggered via their existing was-below/now-above comparison.
- **Hysteresis / minimum spread** (`strategy.py`, `TALONX_QUANT_MIN_MA_SPREAD_PCT`,
  default 0.15%) — a MA crossover only counts if the resulting fast/slow
  spread is at least this fraction of price. Filters a technically-real
  but economically-meaningless crossover, e.g. a $0.03 drift on a $500
  stock (~0.006%, far under 0.15%). Deliberately scoped to the MA cross
  only, not MACD.
- **ATR-move gate** (`strategy.py`, `TALONX_QUANT_ATR_MOVE_MULTIPLIER`,
  default 1.0) — a candidate's own bar (true range: `max(high-low,
  |high-prev_close|, |low-prev_close|)`) must clear this many multiples
  of ATR(14) to count as a genuine directional move rather than routine
  noise on a high-beta name. Applied inside every one of `strategy.py`'s
  own checks, upstream of everything below.
- **Direction-Aware Confluence score** (`strategy.py`'s `_confluence_score`,
  `TALONX_QUANT_CONFLUENCE_SCORE_MIN`, default 2) — 0-3, computed PER
  SIGNAL (not once per bar): +1 for a MACD cross firing that bar, +1 for
  RSI sitting in the extreme zone that actually SUPPORTS this candidate's
  direction (oversold for BULLISH, overbought for BEARISH — an
  **overbought bar earns a BULLISH candidate ZERO points** for this leg,
  since overbought is bearish evidence, not long conviction), +1 for a
  volume surge above threshold. `consumer.py` drops anything below the
  minimum before the per-ticker cooldown is armed.
- **RSI Reversal Curl** (`strategy.py`'s `_check_rsi_volume_setup`) — the
  bullish RSI+volume setup no longer fires the instant RSI first dips
  below `rsi_oversold` (a falling-knife entry with no confirmation the
  selloff has stopped); it waits for RSI to curl back UP and recover
  above the threshold first (`rsi_prev` still below it, `rsi` now at/above
  it), then fires on that recovery bar. The bearish leg (RSI crossing
  INTO overbought) is unchanged.
- **Structural R:R filter** (`strategy.py`'s `_structural_risk_reward`,
  `TALONX_QUANT_PIVOT_STOP_ATR_MULTIPLIER` default 1.5,
  `TALONX_QUANT_MIN_RISK_REWARD_RATIO` default 1.5) — reward is measured
  to the nearest classic floor-trader pivot level (the prior COMPLETED
  regular session's R1 for a bullish candidate, S1 for a bearish one —
  `P = (H+L+C)/3`, `R1 = 2P-L`, `S1 = 2P-H`, computed by
  `indicators.compute_daily_pivots` from the 15-min HTF buffer), not a
  second ATR multiple — a genuine market-derived target, not a
  configuration-constant ratio. Risk is `pivot_stop_atr_multiplier x ATR`.
  `risk_reward_ratio` is `None` (fail-closed, gate drops the candidate)
  until at least one full prior regular session's pivot data is
  available. `stop_price`/`target_price` (`TALONX_QUANT_ATR_STOP_MULTIPLIER`
  default 1.0 for the stop) use this SAME pivot level as the target when
  available, falling back to `TALONX_QUANT_ATR_REWARD_MULTIPLIER` (2.0x
  ATR) only while pivot data is still warming up.
- **Post-loss lockout** (`consumer.py`, `TALONX_QUANT_LOSS_LOCKOUT_SECONDS`,
  default 4500 = 75 min) — `QuantScanner` also subscribes to
  `talonx:paper:trades` (talonx_paper's own execution feed) purely to
  detect a losing SELL. On one, a Redis key `loss_lockout:{TICKER}` locks
  that ticker out for LONGER than, and on top of, the standard cooldown
  below — stopping the engine from repeatedly re-entering a stock that
  just proved it was chopping/declining. Only ever engages for a ticker
  with paper trading enabled (one with it off never publishes an
  execution, so it only ever sees the standard cooldown).
- **Per-ticker cooldown** (`consumer.py`, `TALONX_QUANT_COOLDOWN_SECONDS`,
  default 1200 = 20 min) — a Redis key `cooldown:{TICKER}` locks a ticker
  out of producing ANY further candidate (regardless of signal_type) once
  one is accepted, until the cooldown expires. This is what stops e.g. an
  RSI+volume setup at 15:01 and an unrelated MACD cross at 15:12 on the
  same ticker from both alerting.
- **Batch throttle** (`consumer.py`, `TALONX_QUANT_THROTTLE_WINDOW_SECONDS`
  default 60 / `TALONX_QUANT_THROTTLE_MAX_SIGNALS` default 3) — candidates
  that clear everything above are buffered, not published immediately.
  Every window, the buffer is ranked by `(confluence_score,
  volume_surge_ratio)` — confluence first, volume surge as the tiebreaker
  (a signal with no computed ratio sorts last within its confluence tier)
  — and only the top N are actually published. **This is a deliberate
  latency-for-quality tradeoff**: a signal can sit for up to the full
  window before it's published or dropped — there is no way to guarantee
  "top N of the window" without waiting for the window to close first. A
  final partial-window flush happens on `Ctrl+C`/reconnect so nothing
  buffered is silently lost.

## 2026-08-14 session review: entry blackouts and the volatility gate

Added after combining the execution ledger and dispatch audit trail for
the 2026-08-14 session: a `PYPL` `BUY` at 19:45:17 UTC stopped out 33
seconds later on late-session order-book rebalancing, and `ADC` (a
low-beta REIT) took up an intraday execution slot without ever having
the range to reach an ATR-scaled stop/target.

- **Minimum volatility gate** (`consumer.py`'s `_fails_min_volatility`,
  `TALONX_QUANT_MIN_ATR_PCT`, default 0.25%) — `ATR(14)/price`, as a
  percentage, must clear this floor BEFORE `evaluate_signals` is even
  called for a bar — skips momentum evaluation entirely for a low-beta
  name rather than letting it occupy an execution slot it can't
  profitably fill. Distinct from the ATR-move gate above (that one
  compares a bar's OWN range to its ATR; this one is a per-symbol
  volatility floor independent of any single bar). Does NOT fail closed
  on missing ATR (warm-up) — every RSI/MACD/MA check already requires
  ATR via `_clears_atr_move`, so an unwarmed symbol produces zero signals
  downstream regardless of this gate's answer. Suppression recorded as
  `LOW_VOLATILITY`; metric `failed_min_volatility`.
- **Entry blackout windows** (`session.py`'s `get_entry_blackout`,
  fixed constants, not env-configurable — same treatment the
  pre-market/regular boundary already gets in that module) — a narrower
  classification layered ON TOP of, not folded into, `get_session`'s
  pre-market/regular/closed states: widening `Session` itself to 5 states
  would reset ATR's session-continuity window at 09:30, 09:45, 15:30 AND
  16:00 every day instead of just at the pre-market/regular boundary,
  right during the highest-volume parts of the session.
    - **Opening blackout** (09:30–09:45 ET) — ALL candidates suppressed,
      both directions. Suppression recorded as `OPENING_BLACKOUT`; metric
      `dropped_opening_blackout`.
    - **Closing blackout** (15:30–16:00 ET) — only new **BULLISH**
      candidates suppressed (`_partition`'d out in `consumer.py`, same
      style as the trend/liquidity/news gates below); a genuine
      **BEARISH**/exit candidate still fires, since an open position
      should still be able to exit before `talonx_paper`'s EOD-flatten
      sweep (see [paper.md](paper.md)) closes it out at 15:50 ET anyway.
      Suppression recorded as `CLOSING_BLACKOUT`; metric
      `dropped_closing_blackout`.

## Phase 2 additions: pre-market rules and the 15-min trend gate

- **Session-aware volume-surge threshold** (`session.py`,
  `TALONX_QUANT_PREMARKET_VOLUME_SURGE_RATIO`, default 3.0x) — a stricter
  bar than the regular-session 2.0x default, since pre-market liquidity
  (04:00-09:30 America/New_York) is thin enough that the regular
  threshold isn't a meaningful filter there.
- **Pre-market liquidity gate** (`TALONX_QUANT_PREMARKET_MIN_DOLLAR_VOLUME_PER_MIN`
  default $100,000, `TALONX_QUANT_PREMARKET_MAX_SPREAD_PCT` default
  0.12%) — pre-market-only, fail-closed: dollar volume below the minimum
  or no recent bid/ask quote (`TALONX_QUANT_PREMARKET_QUOTE_STALENESS_SECONDS`,
  default 120s) drops the candidate rather than assuming it passes.
- **Pre-market news-catalyst gate** (`TALONX_QUANT_NEWS_CATALYST_LOOKBACK_HOURS`,
  default 4.0h) — pre-market-only, fail-closed: requires a
  `NewsArticleIngestedEvent` for the ticker within the lookback window
  (published by `talonx_ingest.news.pipeline` to `talonx:news:events`);
  no news ever seen for the ticker never clears this.
- **15-min 200-SMA trend gate** (`TALONX_QUANT_TREND_GATE_ENABLED`,
  `TALONX_QUANT_HTF_SMA_PERIOD` default 200) — regular-session, BULLISH
  candidates only: drops a candidate whose price is at/below the 15-min
  200-period SMA. Built from a second, coarser `RollingBarBuffer`
  aggregated from the same incoming 1-min bars, restricted to Regular
  Trading Hours bars only (`TALONX_QUANT_RTH_ONLY_HTF`, default on) — a
  pre-market 15-min candle is never finalized into this buffer at all. See
  [../bar_buffer_persistence.md](../bar_buffer_persistence.md) for the
  full write-up of this buffer's warm-up, historical pre-seeding, and how
  it survives a restart.

## Implementation notes

- **`buffer.py`** — the rolling OHLCV window is a true calendar-aligned
  1-minute candle, not a raw poll-cycle snapshot: `consumer.py`'s
  `_update_1m_buffer` floor-buckets each incoming tick to the minute and
  builds open/high/low/close/volume purely from the tick's own price,
  updating the SAME row in place (`RollingBarBuffer.add_bar`'s
  same-timestamp-replace behavior) until the wall clock crosses into a new
  minute. Without this, a 12-second poll interval would flood the buffer
  with dozens of near-identical rows for what is, price-action-wise, one
  bar — `min_bars_required` bars now genuinely span that many calendar
  minutes. Every bar is also tagged with its session (pre-market/regular/
  closed). Both buffers (1-min and the 15-min HTF one) are periodically
  checkpointed to `quant.db`, reloaded on restart, and can be instantly
  backfilled via yfinance historical pre-seeding rather than re-warming up
  purely from live ticks — see
  [../bar_buffer_persistence.md](../bar_buffer_persistence.md) for the
  full write-up.
- **`indicators.py`** — computes both the *current* and *previous*
  values for RSI, MACD, and moving averages, not just the latest, since
  edge-triggering/crossover detection needs to know the relationship
  flipped between two consecutive bars, not just where it stands now.
  **Dual Volume Baselines**: the 20-bar volume-surge baseline
  (`TALONX_QUANT_VOLUME_AVG_PERIOD`) is restricted to the trailing
  contiguous run of bars sharing the LATEST bar's session tag (via
  `buffer.py`'s per-bar session tagging and the same `_same_session_tail`
  helper the ATR-reset gate already used) — a regular-session bar's
  volume is never compared against a window still mostly full of thin
  pre-market volume, or vice versa. Goes back to `None` (fresh warm-up)
  right at a session transition until 20 same-session bars accumulate,
  same posture as the ATR reset. `compute_daily_pivots` (Structural R:R,
  above) also lives here, reading the 15-min HTF buffer's
  `regular`-session bars only, grouped by America/New_York calendar date.
- **`strategy.py`** — a single bar update can trigger multiple
  independent signals at once (e.g. an RSI+volume setup and a MACD cross
  on the same bar) — each is evaluated separately rather than collapsed
  into one. All of them still pass through the SAME per-ticker cooldown
  in `consumer.py`, though, since that gate is ticker-scoped, not
  signal_type-scoped.
- This module is deliberately self-contained at the code level: it
  re-declares the `MarketTickEvent` shape locally rather than importing
  `talonx_ingest` Python objects, so the two modules could run as
  separate services/processes without refactoring. It does share the
  same `.env` file (both need the same `TALONX_REDIS_URL`), which is a
  config-sharing decision, not a code dependency.
- **Stage-Gate Metric Funnel** — publishes `metrics:{date}:quant:*`
  counters (`evaluated`, `published`, and one per drop reason:
  `failed_confluence`, `failed_rr_gate`, `failed_trend_gate`,
  `failed_premarket_liquidity`, `failed_loss_lockout`,
  `failed_min_volatility`, `dropped_opening_blackout`,
  `dropped_closing_blackout`) to Redis, read by the Streamlit dashboard's
  Daily Funnel tab — see [dispatch.md](dispatch.md).
- **Rejection Trace Logging** (`consumer.py`'s `_record_rejection`,
  `TALONX_REDIS_REJECTED_CANDIDATES_CHANNEL`, default
  `talonx:quant:rejected`) — every one of `consumer.py`'s gate-drop sites
  (confluence, structural R:R, trend, ATR-move/volatility, entry
  blackouts, cooldown, loss-lockout, batch throttle, pre-market
  liquidity/news-catalyst) now ALSO publishes one `RejectedCandidateEvent`
  PER DROPPED CANDIDATE, alongside the existing local aggregated-count
  persistence (`store.py`'s `suppression_counts`, used by the EOD
  report). `gate` is a stable identifier matching each reason 1:1 (e.g.
  `TREND_GATE` → `trend_gate`, `LOW_RISK_REWARD` → `rr_gate` — see
  `consumer.py`'s `_GATE_NAMES`). Consumed by `talonx_dispatch` purely
  to persist a durable, per-candidate audit trail — see
  [dispatch.md](dispatch.md)'s own Rejection Trace Logging section.

## Long-term (fundamentals) path

See [../phase2-multi-horizon.md](../phase2-multi-horizon.md) for
`fundamentals.py` (ROIC, Piotroski F-Score, FCF Yield, Altman Z-Score
variant) and `fundamental_consumer.py`'s `FundamentalScanner` — a SIBLING
to `QuantScanner`, not a second loop inside it.
