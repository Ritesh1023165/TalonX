# `talonx_quant` — Module 2: Technical & Quantitative Scanner

```
talonx:market:stream (Redis)
    → parse + validate each message as MarketTickEvent
    → only BAR-type events matter (trades/quotes are ignored --
      indicators need OHLCV, not tick-level data)
    → dedup check: has THIS EXACT tick (ticker + its own precise
      timestamp) already been processed? A Redis-replayed/reconnect-
      redelivered duplicate is dropped here, before it can double-count
      volume into a still-forming bucket -- see Bar-Level Ingestion
      Idempotency below
    → append to a per-ticker rolling buffer (bounded, oldest bars drop off);
      the still-FORMING bucket updates in place on every tick, but
      indicators/signals are only ever EVALUATED once that bucket CLOSES
      (the next bucket's first tick arrives) -- see Closed-Bar Evaluation below
    → once enough history exists (120 bars by default) AND a bar has just closed:
        → compute RSI, MACD, SMA fast/slow, volume-surge ratio, and ATR(14)
          (continuous across the session boundary, see below) via pandas_ta
        → evaluate against configured thresholds, EDGE-TRIGGERED (fires
          only on the bar the condition first becomes true, not every
          subsequent bar it remains true), AND requiring this bar's own
          true range to clear 1.0x ATR (a routine, average-sized bar
          doesn't count as a real move):
            - RSI curls back ABOVE 30 (was below, recovers) AND volume > 2x average → bullish (oversold reversal + surge)
            - RSI curls back BELOW 70 (was above, recovers) AND volume > 2x average → bearish (overbought reversal + surge)
            - MACD line crosses its signal line             → bullish/bearish cross
            - fast MA crosses slow MA, spread >= 0.15% of price → golden/death cross
        → every signal that fires carries a DIRECTION-AWARE confluence_score
          (0-3: MACD cross + RSI extreme IN THAT DIRECTION + volume surge --
          an overbought RSI earns a BULLISH candidate 0 points for that leg)
          and a structural risk_reward_ratio (distance to the prior session's
          nearest pivot level / atr_stop_multiplier x ATR -- the SAME
          multiplier the executed stop_price uses)
    → GLOBAL_RISK_DEGRADED check: if a mandatory Redis risk-state write
      (loss-lockout/cooldown) has failed ANYWHERE in this process and
      hasn't yet been reconciled, EVERY ticker's candidates are dropped
      right here, process-wide -- see round 4's GLOBAL_RISK_DEGRADED below
    → UK Operating Window check: outside Mon-Fri 08:00-22:00 Europe/London
      (evaluated fresh from the CURRENT instant, never from when TalonX
      itself started), EVERY ticker's candidates are dropped here too --
      see round 5's UK operating window below
    → candidate signal(s) for a ticker are DROPPED if that ticker is
      currently in POST-LOSS LOCKOUT (75 min default, armed when
      talonx_paper reports a losing SELL for it) or within its standard
      post-signal cooldown (default 20 min) -- a Redis connection/timeout
      error on EITHER check fails CLOSED (treated as "blocked") by
      default, not open, see Fail-Closed Risk Management below
    → candidates below confluence_score_min (default 2) or
      min_risk_reward_ratio (default 1.5) are DROPPED next -- a
      filtered-out candidate is never even queued for the throttle window
    → surviving candidate(s) are buffered for the next throttle flush
      (cooldown is NOT armed yet -- see Post-Publication Cooldown Trigger)
    → every 15s (default), the buffer is ranked by a weighted Composite
      Opportunity Score (confluence + structural R:R + volume surge +
      trend alignment, each normalized to [0,1]); the top 3 (default)
      are each RE-VALIDATED against the LATEST buffered price -- price,
      stop, target, AND ratio are re-derived TOGETHER via the same
      calculate_trade_geometry signal generation itself uses (dropped if
      aged past 30s, if the UK Operating Window has closed since the
      candidate was generated -- UK_SESSION_CLOSED, round 5, checked
      FIRST since a closed window makes everything else moot -- if fresh
      price/ATR/pivot data isn't available at all
      -- FINAL_REVALIDATION_DATA_UNAVAILABLE, round 4 -- or if the
      recalculated R:R has fallen below min_risk_reward_ratio -- see
      round 3's Canonical Trade Geometry below) -- and, if still valid,
      re-checked ONE LAST TIME against GLOBAL_RISK_DEGRADED (round 4)
      before actually publishing to Redis (talonx:signals:quant) AND the
      ticker's cooldown is armed now, for the first time (a Redis SET
      failure while arming EITHER the cooldown or a post-loss lockout
      falls back to an in-memory lock for the same duration AND flips
      GLOBAL_RISK_DEGRADED process-wide, rather than silently not taking
      effect -- see round 3's Fail-Closed Lock Persistence and round 4's
      GLOBAL_RISK_DEGRADED below); the rest are dropped
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
- **RSI Reversal Curl** (`strategy.py`'s `_check_rsi_volume_setup`) —
  BOTH legs now wait for a recovery instead of firing on the initial
  breach: bullish fires when RSI curls back UP above `rsi_oversold`
  (`rsi_prev` still below it, `rsi` now at/above it), and bearish fires
  when RSI curls back DOWN below `rsi_overbought` (symmetric --
  `rsi_prev` still above it, `rsi` now at/below it). A 2026-08-16 quant
  audit flagged the original asymmetric version (bearish fired
  immediately on the INITIAL cross into overbought) as a momentum trap:
  in a trending bull market RSI can sit elevated for hours, and shorting
  the first touch fights the trend rather than confirming a genuine
  reversal.
  **RSI curl vs. RSI confluence, confirmed contract** (Task 28
  `RSI_CONFLUENCE_STATE_BASED_CONFIRMED`, 2026-08-21): the curl defines a
  trigger EVENT (RSI has just exited the extreme zone: `rsi_prev<30 AND
  rsi>=30` bullish / `rsi_prev>70 AND rsi<=70` bearish), while the
  confluence RSI leg above measures current STATE (`rsi<30` bullish /
  `rsi>70` bearish) — complementary conditions by design, so an RSI-curl
  candidate's own RSI value can never satisfy its own confluence RSI leg.
  This is intentional, not a bug or an accidental limitation: it keeps
  the trigger's own bundled evidence (reversal + volume, both already
  required to fire at all) from being counted twice toward its own score.
  Effective requirement: RSI reversal + volume alone produces a candidate
  with confluence=1 (volume only); with `confluence_score_min=2`, a
  same-bar MACD cross is the only other component available to an
  RSI-curl candidate, so one is required for that candidate to clear this
  gate. See `results/task28_rsi_confluence_requirement/` and
  `results/task29_rsi_contract_lock/` for the full requirements analysis,
  and `tests/test_quant_strategy.py`'s "RSI-Curl / Confluence Contract"
  section for the regression tests that lock this in.
- **Signal-family confluence contracts are NOT mathematically symmetric**
  (each family's relationship to its own confluence score is a separate,
  independently-defined contract, not one shared rule applied three ways):
  a MACD-cross candidate's own crossover event automatically supplies its
  MACD confluence point (the trigger check and the confluence-leg check
  are the same underlying condition); an MA-cross candidate's own
  crossover contributes **zero** points (there is no dedicated MA
  confluence component at all); an RSI-curl candidate's own reversal
  event contributes zero points via the RSI leg specifically (state-based
  by design, above) but does contribute one point via the volume leg,
  since volume surge is already required for the trigger to fire. Do not
  assume any one family's behavior generalizes to another.
- **Structural R:R filter** (`strategy.py`'s `_structural_risk_reward`,
  `TALONX_QUANT_ATR_STOP_MULTIPLIER` default 1.5,
  `TALONX_QUANT_MIN_RISK_REWARD_RATIO` default 1.5) — reward is measured
  to the nearest classic floor-trader pivot level (the prior COMPLETED
  regular session's R1 for a bullish candidate, S1 for a bearish one —
  `P = (H+L+C)/3`, `R1 = 2P-L`, `S1 = 2P-H`, computed by
  `indicators.compute_daily_pivots` from the 15-min HTF buffer), not a
  second ATR multiple — a genuine market-derived target, not a
  configuration-constant ratio. `risk_reward_ratio` is `None` (fail-closed,
  gate drops the candidate) until at least one full prior regular
  session's pivot data is available. `target_price` uses the SAME pivot
  level `risk_reward_ratio`'s reward side does when available, falling
  back to `TALONX_QUANT_ATR_REWARD_MULTIPLIER` (2.0x ATR) only while pivot
  data is still warming up.

  **LONG stop geometry is market-structure-primary** (Task 35,
  owner-confirmed ATR-RISK-001: `MARKET_STRUCTURE_PRIMARY` — corrects
  Task 34's `CURRENT_ATR_STOPS_SYSTEMATICALLY_MISALIGNED_WITH_STRUCTURE`
  finding). For a BULLISH candidate, `calculate_trade_geometry` uses the
  same prior-session `S1` pivot support already computed for the target
  side as the PRIMARY stop anchor whenever it is a valid, finite, positive
  number strictly below the candidate's price — `stop_price` is that
  level LITERALLY, with no buffer subtracted around it
  (`STRUCTURAL_BUFFER_REQUIREMENT_NOT_DEFINED`: no existing repository
  requirement defines one, and inventing one would be parameter tuning,
  not spec alignment — see `results/task34_structural_stop_geometry/` and
  `results/task35_structural_stop_implementation/`). Only when no valid
  structural support exists does the stop fall back to the unmodified
  `atr_stop_multiplier x ATR(14, 1-minute)` formula — every `QuantSignal`
  records which path was used (`geometry_path`: `STRUCTURAL_PRIMARY` or
  `ATR_FALLBACK`) and, on the fallback path, why (`fallback_reason`:
  `NO_STRUCTURAL_SUPPORT` / `STRUCTURE_INVALID_OR_NONFINITE` /
  `STRUCTURE_NOT_BELOW_ENTRY`). `risk` (and therefore `risk_reward_ratio`)
  is always derived from the ACTUAL selected stop (`price - stop_price`),
  never a stale ATR-only figure — correcting the stop can therefore
  legitimately change whether a candidate clears the R:R gate, a
  consequence of correctness, not a parameter change. BEARISH is
  unchanged (still `atr_stop_multiplier x ATR`, unconditional) — the
  owner's contract is scoped to LONG stops, since a BEARISH signal never
  opens a new position under the LONG_ONLY lifecycle (Task 25A).
  **`atr_move_multiplier`'s trigger-movement semantics and `min_atr_pct`'s
  regime/volatility-floor semantics are both entirely unchanged and
  out of scope here** — the former was owner-confirmed as-is
  (ATR-TRIGGER-001), the latter remains a separate, not-yet-implemented
  future task (ATR-REGIME-001: `MULTI_TIMEFRAME`, conceptually confirmed,
  no implementation chosen).
- **Post-loss lockout** (`consumer.py`, `TALONX_QUANT_LOSS_LOCKOUT_SECONDS`,
  default 4500 = 75 min) — `QuantScanner` also subscribes to
  `talonx:paper:trades` (talonx_paper's own execution feed) purely to
  detect a losing SELL. On one, a Redis key `loss_lockout:{TICKER}` locks
  that ticker out for LONGER than, and on top of, the standard cooldown
  below — stopping the engine from repeatedly re-entering a stock that
  just proved it was chopping/declining. Only ever engages for a ticker
  with paper trading enabled (one with it off never publishes an
  execution, so it only ever sees the standard cooldown).
- **Per-ticker cooldown** (`consumer.py`'s `_publish_signal`,
  `TALONX_QUANT_COOLDOWN_SECONDS`, default 1200 = 20 min) — a Redis key
  `cooldown:{TICKER}` locks a ticker out of producing ANY further
  candidate (regardless of signal_type) once one PUBLISHES, until the
  cooldown expires. This is what stops e.g. an RSI+volume setup at 15:01
  and an unrelated MACD cross at 15:12 on the same ticker from both
  alerting. Armed on actual publication, not merely on a candidate
  surviving strategy.py's gates -- see Post-Publication Cooldown Trigger
  in the round-2 quant audit section below.
- **Batch throttle + Composite Opportunity Score** (`consumer.py`'s
  `_flush_throttle_window`/`_opportunity_score`, `TALONX_QUANT_THROTTLE_WINDOW_SECONDS`
  default **15s** (down from 60s as of the round-2 quant audit below --
  bounds price/R:R drift before Dynamic R:R Revalidation even runs) /
  `TALONX_QUANT_THROTTLE_MAX_SIGNALS` default 3) — candidates
  that clear everything above are buffered, not published immediately.
  Every window, the buffer is ranked by a weighted composite score and
  the top N are each revalidated against the current price (see the
  round-2 quant audit section's Dynamic R:R Revalidation) before
  actually publishing:
  ```
  score = 0.35 * (confluence_score / 3)
        + 0.30 * min(risk_reward_ratio / 5.0, 1.0)
        + 0.20 * min(volume_surge_ratio / 10.0, 1.0)
        + 0.15 * (1.0 if trend_aligned else 0.5 if trend_aligned is None else 0.0)
  ```
  All four weights and both caps are env-configurable
  (`TALONX_QUANT_OPPORTUNITY_{CONFLUENCE,RR,VOLUME,TREND}_WEIGHT`,
  `TALONX_QUANT_OPPORTUNITY_{RR,VOLUME}_CAP`). Replaces the original
  `(confluence_score, volume_surge_ratio)` tuple-sort (2026-08-16 quant
  audit, P1): sorting on the RAW volume-surge ratio as a tiebreaker
  systematically favored penny/meme-stock pumps — which can post
  enormous surge ratios purely because their baseline volume is thin —
  over a higher-conviction, better-risk-reward setup on a liquid
  large-cap with a smaller relative surge. Normalizing every factor to
  `[0, 1]` before weighting means no single unbounded input can dominate
  the ranking on scale alone. **This is a deliberate latency-for-quality
  tradeoff**: a signal can sit for up to the full window before it's
  published or dropped — there is no way to guarantee "top N of the
  window" without waiting for the window to close first. A final
  partial-window flush happens on `Ctrl+C`/reconnect so nothing buffered
  is silently lost.

## 2026-08-16 quant audit: closed-bar evaluation and continuous ATR

An independent quantitative/architectural audit of the 2026-08-16
requirement-doc fixes above (direction-aware confluence, structural R:R,
RSI reversal curl) surfaced two further P0-severity correctness gaps and
a P1 volatility-modeling flaw:

- **Closed-Bar Evaluation** (`consumer.py`'s `_handle_market_tick`) —
  indicators/signals used to be evaluated on EVERY tick, including a
  still-forming (not yet closed) 1-minute bar: `_update_1m_buffer`
  already updated the current bucket's OHLCV in place on every tick (for
  other consumers, e.g. the pre-market liquidity gate's dollar-volume
  read), but `compute_indicators`/`evaluate_signals` ran against that
  SAME partial, still-moving candle. An RSI/MACD/MA crossing could flash
  true on an early tick within the minute and be false again by the
  bar's actual close — a "phantom trigger"/repaint, not just extra
  noise, since the published signal's own indicator values (rsi, macd,
  etc.) reflected a price that was never the bar's final one. Fixed by
  gating evaluation on `bar_just_closed`: the buffer's dataframe is
  captured the INSTANT a symbol's next bucket's first tick arrives —
  before that tick's own bucket is written — so its last row is always
  the bar that just closed, never the one just starting. The buffer
  itself still updates every tick unchanged; only the evaluation trigger
  changed.
- **Harmonized risk distance** — see the Structural R:R filter bullet
  above; `_structural_risk_reward`'s gate and `_stop_target_prices`'
  executed stop now share one `atr_stop_multiplier`, closing a
  discrepancy where a candidate could pass the R:R gate on a WIDER risk
  distance than the stop it was actually published/executed with.
- **RSI Reversal Curl made symmetric** — see the RSI Reversal Curl
  bullet above; the bearish leg now waits for a recovery back below
  `rsi_overbought` too, instead of firing on the initial cross in (a
  momentum trap in a trending market).
- **Continuous ATR across the session boundary** (`indicators.py`'s
  `compute_indicators`) — ATR/`bar_true_range` used to reset at the
  regular-session open the same way the volume-surge baseline still
  does (`_same_session_tail`), restricting the ATR window to only the
  bars since 09:30 ET. Right after the open, that meant computing ATR
  from a handful of opening-range bars — which typically run 3-5x wider
  than midday trading — producing an artificially inflated, unstable
  baseline exactly when the ATR-move gate and structural R:R's risk
  distance most need a stable read. Liquidity genuinely resets at a
  session boundary (pre-market participation is thin); true price range
  doesn't, so ATR is now computed from the FULL buffer, continuous
  across the boundary. The volume baseline is UNCHANGED and still
  session-restricted — these are two different concepts (a rolling
  volatility measure vs. a session-scoped liquidity measure) that
  happened to share one reset mechanism before this fix, not one that
  should.
- **Dependency pinning** (`talonx_quant/requirements.txt`) — floored
  `pandas_ta` at `0.4.71b0` (confirmed numpy-2.0-compatible) with an
  explicit `numpy>=2.0,<3.0` pin, replacing the prior
  `pandas_ta>=0.3.14b0` floor, which references the removed `numpy.NaN`
  alias and previously required a developer to manually patch it before
  import against a modern NumPy — a fragile, easy-to-forget workaround
  now made unreachable by a correct dependency floor instead.

## 2026-08-16 quant audit (round 2): throttle latency, risk-state integrity, and ingest idempotency

A follow-up audit of the round-1 fixes above identified four further
gaps in execution correctness and stream-processing robustness:

- **Dynamic R:R Revalidation** (`consumer.py`'s `_revalidate_candidate`,
  `TALONX_QUANT_MAX_CANDIDATE_AGE_SECONDS` default 30s) — a candidate
  selected at throttle flush is re-checked against the LATEST buffered
  close price before it actually publishes, not trusted as-generated.
  Dropped as `EXPIRED_IN_THROTTLE_QUEUE` if `now - signal_generated_at`
  exceeds the age limit; otherwise the full trade geometry (stop, target,
  risk, reward, ratio — see `calculate_trade_geometry` in the round-3
  section below) is recalculated against the fresh price and dropped as
  `RR_DEGRADED_DURING_THROTTLE` if the recalculated ratio has fallen
  below `min_risk_reward_ratio` (or couldn't be confirmed at all, e.g.
  price has drifted through the pivot level). A candidate that can't be
  revalidated at all (no fresh buffered price yet, or missing atr/pivot
  inputs) is published as-generated rather than dropped purely for
  missing fresher data. The published `QuantSignal.price`/`stop_price`/
  `target_price`/`risk_reward_ratio` all reflect the SAME revalidated
  geometry; `signal_age_ms` records how old the candidate was at that
  moment. Paired with a shorter throttle window
  (`TALONX_QUANT_THROTTLE_WINDOW_SECONDS`, **60s → 15s default**) to
  bound how much drift can accumulate before revalidation even runs.
- **Post-Publication Cooldown Trigger** (`consumer.py`'s
  `_publish_signal`) — the per-ticker cooldown (`cooldown:{TICKER}`) is
  now armed ONLY once a candidate actually clears the throttle window's
  ranking AND revalidation and successfully publishes — not merely once
  it survives strategy.py's own gates. A candidate the batch throttle
  (or revalidation) later drops no longer burns the ticker's 20-minute
  cooldown slot and blocks a later, better candidate for a signal that
  was never actually published. Safe against the original design's "two
  candidate batches queuing in one window" concern because Closed-Bar
  Evaluation (round 1) already caps a ticker to at most one candidate
  batch per closed 1-minute bar, structurally, independent of when
  cooldown is armed.
- **Fail-Closed Risk Management** (`consumer.py`'s
  `_handle_risk_check_failure`, `TALONX_QUANT_RISK_FAIL_CLOSED` default
  `true`) — a Redis connection/timeout error inside `_is_on_cooldown`/
  `_is_loss_locked_out` used to be treated as "not on cooldown"/"not
  locked out" (fail OPEN), letting candidates keep publishing during
  exactly the risk-state blackout these two gates exist to prevent.
  Logged at `CRITICAL` (not a routine warning) and, by default, now
  returns `True` (treat the ticker as BLOCKED) instead — an explicit,
  non-default opt BACK into fail-open behavior is still available via
  the config flag, for operators who've made that tradeoff deliberately.
  Also records a `RISK_STORE_UNAVAILABLE_FAIL_CLOSED` rejection trace
  event so an outage is visible in the audit trail, not just the logs.
- **Bar-Level Ingestion Idempotency** (`consumer.py`'s `_is_new_bar_tick`,
  `TALONX_QUANT_BAR_DEDUP_TTL_SECONDS` default 600s) — every incoming
  BAR tick is checked against a dedup key
  (`processed_bar:{TICKER}:{tick's own precise timestamp}`, a Redis
  `SETNX` with a TTL) BEFORE it's fed into the rolling buffer at all. A
  stream replay or Pub/Sub reconnect redelivering the EXACT same tick is
  silently dropped (metric `dropped_duplicate_bars`) rather than
  double-counting that tick's volume into a still-forming bucket's
  running accumulation — `RollingBarBuffer.add_bar`'s own upsert-by-
  timestamp only dedupes the FINAL row per bucket, not each tick feeding
  it, so a genuinely duplicate tick could otherwise inflate a bucket's
  volume before it ever closes. Keyed on the tick's own PRECISE
  timestamp (not the floor-bucketed minute), so legitimate accumulation
  — multiple genuinely different ticks landing in the same forming
  minute — is unaffected; only an exact repeat is caught. Falls back to
  a bounded in-memory set (last 200 keys per symbol) when Redis itself
  is unavailable — deliberately best-effort, NOT fail-closed, since a
  duplicate slipping through during a Redis outage costs at most one
  double-counted tick's volume, not a bypassed risk control.

## 2026-08-16 quant audit (round 3): canonical trade geometry, lock persistence, and the HTF-unavailable gate

A second follow-up audit of the round-2 fixes above (itself independently
re-checking the code, not just the requirement doc) found three more
correctness gaps:

- **Canonical Trade Geometry** (`strategy.py`'s
  `calculate_trade_geometry`) — round 2's `_revalidate_candidate` only
  recalculated `price` and `risk_reward_ratio` against the fresh buffered
  close, leaving `stop_price`/`target_price` pinned to the ORIGINAL,
  now-stale entry price. A published signal could therefore show a ratio
  measured against one price alongside a stop/target measured against a
  different one — an internally inconsistent trade. `calculate_trade_geometry`
  is now the single function that derives stop/target/risk/reward/ratio
  from an entry price, used both by `strategy.py`'s `_build_signal` (via
  thin `_structural_risk_reward`/`_stop_target_prices` wrappers, kept for
  their existing unit tests) at signal generation and directly by
  `consumer.py`'s `_revalidate_candidate` at throttle-flush time — so
  price, stop, target, and ratio always move together, structurally.
- **Fail-Closed Lock Persistence** (`consumer.py`'s `_arm_fallback_lock` /
  `_in_memory_lock_active`) — round 2's Fail-Closed Risk Management only
  covered a Redis error while CHECKING the cooldown/loss-lockout keys;
  a Redis error while ARMING one (the `SET` in `_start_cooldown`/
  `_start_loss_lockout`) still only logged a warning and moved on, so the
  lock could silently never take effect — a losing trade's mandatory
  75-minute lockout, or a just-published signal's 20-minute cooldown,
  simply wouldn't be enforced if that one `SET` call failed. Both now
  fall back to an in-memory, process-local lock for the same ticker and
  duration when the `SET` fails (logged `CRITICAL`), checked on every
  subsequent `_is_on_cooldown`/`_is_loss_locked_out` call ahead of the
  Redis read, until it naturally expires or a later `SET` for that ticker
  actually succeeds (which clears the fallback). This is a same-process
  safety net, not cross-restart durable state — the underlying Redis
  outage still needs fixing, but a candidate can no longer publish (or a
  losing ticker re-enter) purely because one lock-arming write failed.
- **HTF-Unavailable Trend Gate** (`consumer.py`'s `_trend_gate_applicable`,
  reason `HTF_DATA_UNAVAILABLE`) — `QuantSignal.trend_aligned=None` has
  always meant two different things: "the trend gate doesn't apply to
  this candidate" (bearish, pre-market, or the gate disabled) and "the
  gate DOES apply but the 15m-200-SMA buffer hasn't warmed up to 200 bars
  yet." The old `trend_aligned is not False` filter treated both
  identically, so a regular-session BULLISH candidate could publish with
  ZERO trend confirmation whenever the HTF buffer was still cold — not
  merely "gate not applicable," but "gate applicable, answer unknown,
  passed anyway." A regular-session bullish candidate with a
  `trend_gate_enabled` gate and `htf_sma_200` still `None` is now
  rejected as `HTF_DATA_UNAVAILABLE` (its own gate/reason, distinct from
  `TREND_GATE`'s "evaluated and failed") instead.

## 2026-08-16 quant audit (round 4): global degraded state, final-revalidation data availability, and deployment-model correctness

A third follow-up audit, this time explicit about the deployment model
this process actually runs under: **not a 24x7 service**. `talonx_quant`
(via `run_talonx.py`) is a host process, NOT Dockerised — only Redis is
(`docker-compose.yaml`'s `talonx-redis`, already running with AOF
persistence (`--appendonly yes`) and a named volume (`talonx-redis-data:
/data`), so no persistence changes were needed there. TalonX itself is
started/stopped by `scripts/start_talonx.ps1`/`stop_talonx.ps1`, normally
on a Monday-Friday-only Windows Scheduled Task
(`scripts/register_scheduled_tasks.ps1`, a WEEKLY trigger scoped to
`-DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday` — NOT `-Daily`,
which would also fire on Saturday/Sunday) covering ~08:00-22:00 UK local
time by default — Task Scheduler's own weekly trigger already handles
the GMT/BST transition, so no new timezone logic was needed for the
scheduler itself. Both this process and Redis are expected to be
stopped outside that window. Three fixes, all scoped to that model (see
`consumer.py`'s own module docstring, "Round-4 quant audit" section, for
the full technical writeup):

- **GLOBAL_RISK_DEGRADED** (`consumer.py`'s `_enter_risk_degraded`/
  `_reconcile_risk_state`/`_verify_redis_persistence`) — round 3's
  per-ticker in-memory fallback lock (`_arm_fallback_lock`) was a real
  improvement over silently logging a warning, but it's still scoped to
  the ONE ticker whose write failed: a Redis SET failing for AAPL's
  cooldown says nothing about whether MSFT or NVDA are safe to trade, it
  says Redis itself can't currently be trusted. Every mandatory-write
  failure now ALSO flips a single process-wide `self._risk_degraded`
  flag, checked early (`_handle_market_tick`, per-ticker, cheap) and
  authoritatively (`_publish_signal`, the one funnel every actual
  publish goes through for every ticker — also catches a candidate
  already sitting in the throttle queue from before degradation began).
  Cleared ONLY by a CONFIRMED Redis write-verify
  (`_verify_redis_persistence` — a write-then-readback roundtrip; PING
  succeeding is deliberately NOT sufficient), run at the start of every
  `_connect_and_listen` call (both a genuine process startup and every
  reconnect after a dropped connection) and, while already degraded, on
  every `_checkpoint_loop` tick (piggybacking on that ALREADY-EXISTING
  periodic loop rather than adding a new one — deliberately not a 24x7
  recovery daemon; both retry paths only run for the life of one
  connected session). `GLOBAL_RISK_DEGRADED` itself is NEVER written to
  Redis — it's this process's own in-memory safety state; it disappears
  on the normal ~22:00 shutdown (acceptable, per this module's own
  docstring) and is re-derived from scratch on the next run/reconnect.
- **Per-ticker locks need no restart-time reconciliation of their own**
  — this was already correct before round 4 and didn't need new code:
  `_is_on_cooldown`/`_is_loss_locked_out` always read
  `EXISTS cooldown:{TICKER}`/`loss_lockout:{TICKER}` LIVE from Redis,
  never from a process-local cache, so a Friday-still-valid TTL'd lock
  is honoured automatically the instant a fresh Monday process starts
  checking again, and an expired one is equally simple (Redis's own TTL
  already removed the key). Existing TTL/cooldown/lockout DURATIONS are
  completely unchanged.
- **Final Revalidation Data Availability** (`consumer.py`'s
  `_revalidate_candidate`) — previously, when fresh price/ATR/pivot data
  wasn't available at throttle-flush time, the candidate published
  AS-GENERATED (its original, by-then-unverified geometry). It's now
  rejected instead, as `FINAL_REVALIDATION_DATA_UNAVAILABLE` — final
  publication must be based on a VERIFIED current trade geometry, never
  an assumed-still-good stale one.

**Explicitly NOT changed:** any of the frozen strategy parameters (RSI
30/70, volume 2x/premarket 3x, ATR move 1x, ATR stop 1.5x, min R:R 1.5,
cooldown 20min, throttle 15s, max candidate age 30s, min confluence 2/3,
opportunity-score weights 35/30/20/15) — this was a correctness/
reliability patch only. Also explicitly not built: a 24x7 Redis/TalonX
monitoring daemon, a new scheduler, or Dockerising TalonX — none of those
match the actual deployment model above.

A theoretical check-then-act race between `_is_on_cooldown`'s read and
`_start_cooldown`'s write for the SAME ticker was reviewed (the batch
throttle's flush runs as a separate task from the main message loop) and
found to be structurally prevented rather than needing a distributed
lock: Closed-Bar Evaluation already caps a ticker to at most one
candidate batch per closed 1-minute bar, so the earliest a second batch
for the same ticker could even be queued is the NEXT bar close, ≥60s
later — far longer than the few-millisecond revalidate→publish→arm-
cooldown sequence for the first batch. Redis Pub/Sub itself provides no
delivery guarantee (not even at-least-once) for the published
`QuantSignal` — a disconnected subscriber simply never receives it. This
is a stated, accepted limitation of Pub/Sub as a transport, not a gap
closed by this module; downstream consumers of `talonx:signals:quant`
already treat delivery as best-effort, same as every other Pub/Sub
channel in this project. Bar-Level Ingestion Idempotency (round 2) is
this module's actual exactly-once guarantee, and it's scoped to INPUT
tick processing, not to the outbound publish.

## 2026-08-16 quant audit (round 5): UK operating window, arbitrary startup/shutdown safety

**"08:00-22:00 Monday-Friday is a trading-session rule, not an
application-startup rule."** TalonX may be started at any time of day —
mid-session, before the window opens, on a weekend, or after an
unplanned crash — and must never assume it was launched at exactly
08:00. This round adds an explicit, dynamically-evaluated gate for
that, on top of (not instead of) round 4's `GLOBAL_RISK_DEGRADED`; both
must be satisfied before a signal actually publishes.

- **`is_operating_window_open`** (`session.py`) — a new, orthogonal
  function alongside `get_session`/`get_entry_blackout` (which classify
  the US MARKET's own ET session for a bar's timestamp): this one
  answers "is TalonX allowed to publish signals right now," evaluated
  from `Europe/London` via `zoneinfo` (DST-aware — the boundary stays
  08:00/22:00 UK LOCAL time across the GMT/BST transition, never a fixed
  UTC offset), Mon-Fri only, Saturday/Sunday unconditionally closed
  regardless of time of day. Deliberately stateless and evaluated FRESH
  on every call from the current wall-clock instant (or an explicit
  `timestamp` for testing) — never cached, never derived from when the
  process itself started. Boundary semantics match `get_session`'s own
  half-open-interval convention: `08:00:00` local is OPEN (inclusive),
  `22:00:00` local is CLOSED (exclusive).
- **Two gates in `consumer.py`**, mirroring `GLOBAL_RISK_DEGRADED`'s own
  early/authoritative split: an early, cheap check in
  `_handle_market_tick` (`UK_SESSION_CLOSED`, before any ticker-specific
  gate), and the AUTHORITATIVE check in `_revalidate_candidate` — a
  candidate generated just before the window closes (e.g. 21:59:50) can
  still be sitting in the throttle buffer past the actual close
  (22:00:00), so the early per-tick check alone can't catch that; final
  revalidation re-checks the window immediately before publish.
- **No new scheduler, daemon, or 24x7 process** — the check is a pure
  function of the current instant, called inline wherever publication is
  about to happen. A "random restart" (crash mid-session, restart on a
  weekend, restart hours after a scheduled 08:00 start) needs no special
  handling: a freshly-constructed `QuantScanner` simply evaluates the
  current window on its very first tick, exactly like every other tick
  — same reasoning round 4 already established for per-ticker Redis
  locks needing no restart-time reconciliation of their own.
- **Session closure doesn't touch state** — at 22:00 (or any other
  window-closed instant), nothing is deleted, reset, or cleared: Redis
  TTLs, per-ticker cooldown/loss-lockout locks, and bar-dedup state are
  completely untouched; only NEW publication is prevented. The existing
  deployment architecture (`docs/running.md` / `scripts/start_talonx.ps1`
  + `docker-compose.yaml`'s Redis-only Compose service) is unchanged —
  this round is purely an in-process gating rule, not a deployment change.

## 2026-08-16 quant audit (round 6): scheduled-task weekday scoping

**Critical design principle: the scheduled task controls PROCESS
LIFECYCLE; the TalonX application itself controls whether trading is
currently PERMITTED.** Round 5 above already made the application side
of that true (`is_operating_window_open`, checked independently of when
or how the process started). This round fixes the one place the OTHER
half of that statement wasn't yet true: `scripts/register_scheduled_tasks.ps1`
used `New-ScheduledTaskTrigger -Daily`, which fires every day INCLUDING
Saturday/Sunday — harmless in practice (round 5's gate would still have
refused to publish), but pointless: no reason to leave the process
running unattended on a weekend at all. Fixed to
`New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,
Thursday,Friday`, and `-StartTime`'s default corrected from `10:00` to
match the actual trading-session open, `08:00` (`-StopTime`'s `22:00`
default was already correct). Windows Task Scheduler's weekly triggers
are just as DST-aware as its daily ones were (a local-time trigger of
any recurrence type auto-adjusts for the machine's own GMT/BST changes),
so this is a day-of-week fix only, nothing timezone-related changed.
This script remains explicitly NOT the mechanism that keeps trading
safe — it merely avoids leaving the process running unattended outside
the normal window on a machine that's otherwise always on. A manual
`.\scripts\start_talonx.ps1` at any arbitrary time (Saturday, or any
other outside-window instant) still leaves the process running with
trading correctly disabled by round 5's gate.

## 2026-08-16 quant audit (round 7): intra-flush cooldown re-check

**P1 — same-ticker multiple candidates could bypass cooldown within one
throttle flush.** `strategy.py` deliberately allows multiple independent
signal TYPES to fire off the same closed bar for the same ticker (a MACD
cross AND an RSI/volume setup on the same bar, say), so two candidates
for one ticker could legitimately land in the same throttle batch.
`_flush_throttle_window`'s publish loop (`consumer.py`) revalidated and
published each `released` candidate in sequence with no cooldown
re-check in between -- the FIRST candidate for a ticker would publish
and arm `cooldown:{TICKER}` (in `_publish_signal`'s Post-Publication
Cooldown Trigger), but the SECOND candidate for that same ticker, having
already cleared the cooldown check back when it first entered the queue
(up to `throttle_window_seconds` earlier, in `_handle_market_tick`),
sailed straight through to publish too -- two signals for one ticker out
of a single flush, defeating the per-ticker cooldown entirely.

Fixed with a single `await self._is_on_cooldown(signal.ticker)` re-check
at the top of the publish loop, immediately before each candidate is
allowed to proceed toward `_revalidate_candidate`/`_publish_signal` --
catches a cooldown armed by an EARLIER candidate in the SAME loop
iteration, not just one that predates the flush. Placed before
revalidation (not just before publish) so a candidate that's already
doomed to a `COOLDOWN` rejection skips the wasted current-price/geometry
re-fetch too. Reuses `_is_on_cooldown` exactly as-is -- same
fail-closed-on-Redis-error policy (`config.risk_check_fail_closed`) and
the same in-memory fallback lock as every other cooldown check in this
module; no new fail-open path, and `GLOBAL_RISK_DEGRADED` still applies
as a second line of defense if a cooldown-arming Redis write itself
fails. Throttle ranking/capacity (`released`/`dropped`) is unchanged --
a cooldown-rejected candidate was still correctly ranked into the
released batch, it just fails this downstream check, same as an
existing revalidation failure already could.

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
  would reset the volume-surge baseline's session-scoped window at
  09:30, 09:45, 15:30 AND 16:00 every day instead of just at the
  pre-market/regular boundary, right during the highest-volume parts of
  the session (ATR itself is exempt from this concern entirely — see
  the Continuous ATR fix in the 2026-08-16 quant audit section above).
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
  it survives a restart. A candidate this gate applies to (bullish,
  regular session, gate enabled) whose 200-SMA isn't warmed up yet is
  rejected as `HTF_DATA_UNAVAILABLE`, distinct from `TREND_GATE`'s
  "evaluated below the SMA and failed" — see round 3's HTF-Unavailable
  Trend Gate above.

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
  full write-up. **Aggregation vs. evaluation are deliberately separate**
  (Closed-Bar Evaluation, above): the buffer keeps updating the
  still-forming bucket in place every tick (other consumers, e.g. the
  pre-market liquidity gate, want that freshness), but
  `_handle_market_tick` only ever runs `compute_indicators`/
  `evaluate_signals` once a bucket has fully CLOSED, never against the
  partial one.
- **`indicators.py`** — computes both the *current* and *previous*
  values for RSI, MACD, and moving averages, not just the latest, since
  edge-triggering/crossover detection needs to know the relationship
  flipped between two consecutive bars, not just where it stands now.
  **Dual Volume Baselines**: the 20-bar volume-surge baseline
  (`TALONX_QUANT_VOLUME_AVG_PERIOD`) is restricted to the trailing
  contiguous run of bars sharing the LATEST bar's session tag (via
  `buffer.py`'s per-bar session tagging and the `_same_session_tail`
  helper) — a regular-session bar's volume is never compared against a
  window still mostly full of thin pre-market volume, or vice versa.
  Goes back to `None` (fresh warm-up) right at a session transition
  until 20 same-session bars accumulate. **ATR is deliberately NOT
  restricted this way** (see the 2026-08-16 Continuous ATR fix above) —
  liquidity resets at a session boundary, true price range doesn't, so
  `_same_session_tail` is now used ONLY for this volume baseline, not
  ATR. `compute_daily_pivots` (Structural R:R, above) also lives here,
  reading the 15-min HTF buffer's `regular`-session bars only, grouped
  by America/New_York calendar date.
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
  **Reading the rejection counts** (clarified Task 27/29, 2026-08-21):
  both the local aggregated `suppression_counts` and the per-candidate
  `RejectedCandidateEvent` record only the FIRST gate that dropped a
  given candidate, in the fixed gate order above — a `LOW_CONFLUENCE`
  count means confluence was the first gate that rejected those
  candidates; it does NOT mean they would otherwise have passed every
  later gate (R:R, trend, entry blackouts, etc.). Some candidates
  counted under an earlier gate would also have independently failed a
  downstream one; see
  `results/task27_strategy_feasibility_audit/first_failure_vs_all_failures.csv`
  for a worked example. This does not change gate order or the metrics
  themselves, only how the counts should be read.

## Long-term (fundamentals) path

See [../phase2-multi-horizon.md](../phase2-multi-horizon.md) for
`fundamentals.py` (ROIC, Piotroski F-Score, FCF Yield, Altman Z-Score
variant) and `fundamental_consumer.py`'s `FundamentalScanner` — a SIBLING
to `QuantScanner`, not a second loop inside it.
