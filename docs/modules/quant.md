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
            - RSI crosses under 30 AND volume > 2x average → bullish (oversold + surge)
            - RSI crosses over 70 AND volume > 2x average  → bearish (overbought + surge)
            - MACD line crosses its signal line             → bullish/bearish cross
            - fast MA crosses slow MA, spread >= 0.15% of price → golden/death cross
        → every signal that fires on a bar carries that bar's confluence_score
          (0-3: MACD cross + RSI extreme + volume surge) and risk_reward_ratio
          (ATR-scaled reward / talonx_paper's stop-loss distance)
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
- **Confluence score** (`strategy.py`, `TALONX_QUANT_CONFLUENCE_SCORE_MIN`,
  default 2) — a bar-level score, 0-3: +1 each for a MACD cross firing
  that bar, RSI sitting in its extreme zone, and a volume surge above
  threshold. Computed once per bar and attached to every signal that
  fires on it; `consumer.py` drops anything below the minimum before the
  per-ticker cooldown is armed.
- **Risk/reward filter** (`strategy.py`, `TALONX_QUANT_ATR_STOP_MULTIPLIER`
  default 1.0, `TALONX_QUANT_ATR_REWARD_MULTIPLIER` default 2.0,
  `TALONX_QUANT_MIN_RISK_REWARD_RATIO` default 1.5) — stop and target are
  both explicit ATR multiples (1x/2x by default), giving every signal a
  real dollar `stop_price`/`target_price`, not just the ratio. A
  candidate below the minimum ratio is dropped alongside the confluence
  filter, before the cooldown lock.
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
  aggregated from the same incoming 1-min bars. See
  [../bar_buffer_persistence.md](../bar_buffer_persistence.md) for the
  full write-up of this buffer's warm-up time (~50 continuous hours) and
  how it survives a restart.

## Implementation notes

- **`buffer.py`** — the rolling OHLCV window is deliberately deduped by
  timestamp: yfinance polling re-sends a snapshot of the *current* bar
  every poll cycle (it's not a discrete new-bar push like a WebSocket
  aggregate), so without this the buffer would fill with dozens of
  near-identical rows for what is, price-action-wise, one bar. Both
  buffers (1-min and the 15-min HTF one) are periodically checkpointed to
  `quant.db` and reloaded on restart — see
  [../bar_buffer_persistence.md](../bar_buffer_persistence.md).
- **`indicators.py`** — computes both the *current* and *previous*
  values for RSI, MACD, and moving averages, not just the latest, since
  edge-triggering/crossover detection needs to know the relationship
  flipped between two consecutive bars, not just where it stands now.
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
  `failed_premarket_liquidity`, `failed_loss_lockout`) to Redis, read by
  the Streamlit dashboard's Daily Funnel tab — see
  [dispatch.md](dispatch.md).

## Long-term (fundamentals) path

See [../phase2-multi-horizon.md](../phase2-multi-horizon.md) for
`fundamentals.py` (ROIC, Piotroski F-Score, FCF Yield, Altman Z-Score
variant) and `fundamental_consumer.py`'s `FundamentalScanner` — a SIBLING
to `QuantScanner`, not a second loop inside it.
