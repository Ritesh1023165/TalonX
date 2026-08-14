# `talonx_core` — Module 4: Core Event Bus & Decision Engine

```
talonx:signals:quant (Redis)  ──┐
                                 ├──► talonx_core: update per-ticker state
talonx:reports:brain (Redis)  ──┘     (TickerCorrelator -- freshest
                                        QuantSignal + freshest
                                        ResearchReport seen for that
                                        ticker, each timestamped by
                                        RECEIPT time)
                                       │
                                       ▼
                          re-run the Decision Matrix for that ticker
                          (decision.py -- pure function, no I/O):
                            1. both halves present? both still fresh
                               (within TALONX_CORE_CORRELATION_WINDOW)?
                            2. ticker not in cooldown
                               (TALONX_CORE_TICKER_COOLDOWN)?
                            3. report.is_degraded?
                               yes → action = DEGRADED_QUANT_ALERT
                                     (skips step 4 entirely)
                               no  → research confidence >=
                                     TALONX_CORE_MIN_CONFIDENCE, and verdict
                                     is directional (not neutral/
                                     insufficient)?
                          → any "no" at steps 1-2, or failing step 4 = no
                            alert, silently
                                       │
                                       ▼
                    (skipped for a degraded report) quant direction ==
                    research verdict?
                      yes → CONFIRMED_BULLISH / CONFIRMED_BEARISH
                      no  → CONTRADICTED (quant and research disagree)
                                       │
                                       ▼
                          5. state-transition + price-delta gate: is this
                             action the SAME as the last alert actually
                             dispatched for this ticker? If so, has price
                             moved >= TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT
                             (default 1.0%) since that alert? A genuine
                             transition (or a first-ever alert) always
                             passes; a repeat of the same action without
                             enough price movement is suppressed -- runs
                             IN ADDITION to the cooldown at step 2, not
                             instead of it.
                                       │
                                       ▼
                     publish ActionableAlert to Redis
                     (talonx:alerts:dispatch), record that ticker's new
                     cooldown/action/price
```

- **`state.py`** — `TickerCorrelator` holds one `TickerState` per ticker,
  in memory, for the life of the process. Freshness is judged from when
  *talonx_core itself* received each half of the pair, not the payload's
  own internal timestamp -- this stays correct regardless of clock skew
  between producers or how long a message sat queued upstream (which, for
  `talonx_brain`, can be minutes under its Gemini rate limit -- see
  [brain.md](brain.md)).
- **`store.py`** — `TickerStateStore`, SQLite-backed (stdlib, same choice
  `talonx_ingest.storage.ledger` makes), one row per ticker, upserted on
  every update -- now including `last_alert_action`/`last_alert_price` for
  the re-trigger gate above, added via the same idempotent
  `PRAGMA table_info` + `ALTER TABLE` migration pattern used by
  `talonx_watchlist/store.py`, so a pre-existing `core_state.db` upgrades
  in place rather than erroring. Fixes a real gap: without it, a restart
  mid-correlation (a `QuantSignal` received but its `ResearchReport`
  hasn't landed yet -- routine given `talonx_brain`'s multi-minute lag)
  would silently lose that half of the pair forever. `consumer.py`
  rehydrates the correlator from it at startup and writes through on
  every update; `run.py`
  constructs it (`TALONX_CORE_ENABLE_PERSISTENCE`, default on;
  `TALONX_CORE_STATE_DB`, default `~/.talonx/core_state.db`) and degrades
  gracefully (logs a warning, continues in-memory-only) if the file can't
  be opened, same philosophy as Redis publishing elsewhere in this
  project. Calls are made synchronously, NOT via `asyncio.to_thread` --
  `sqlite3`'s default `check_same_thread=True` would break under a
  different worker thread, same reasoning `IngestionLedger` documents for
  its own connection.
- **`decision.py`** — the Decision Matrix itself: a pure function over a
  `TickerState` snapshot, no I/O, so it's trivial to unit test in
  isolation from Redis/asyncio. Deliberately narrow: only
  `CONFIRMED_BULLISH`, `CONFIRMED_BEARISH`, `CONTRADICTED`, and
  `DEGRADED_QUANT_ALERT` ever reach the alerts channel -- a
  neutral/insufficient-context verdict, or one below the confidence gate,
  is UNCONFIRMED and produces no alert at all, keeping
  `talonx:alerts:dispatch` purely actionable rather than a firehose.
  `CONTRADICTED` is treated as at least as noteworthy as agreement (its
  severity floor is WARNING, never INFO) -- a technical signal and the
  research disagreeing is arguably the more actionable outcome of the
  two, not a "nothing to report" case.
- **State-transition + price-delta re-trigger gate** — a second guardrail
  on top of the time-based cooldown (both must pass, neither replaces the
  other): `TickerState` now also tracks the `action` and `triggering
  signal price` of the last alert actually dispatched for a ticker. A new
  evaluation that would produce the SAME action as that last alert is
  suppressed unless price has moved at least `TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT`
  (default 1.0%) since then; a genuine transition (including the very
  first alert for a ticker) always passes regardless of price. Persisted
  the same way as everything else in `store.py` (see below).
- **`report.is_degraded` bypass** — `talonx_brain` publishes a
  specially-flagged `ResearchReport` (verdict `neutral`, confidence 0.0,
  `is_degraded=True`) when its LLM call fails AND it has no cached report
  to fall back on (see [brain.md](brain.md)'s caching section).
  `decision.py` recognizes this flag and skips the confidence/verdict
  matrix entirely, always producing `DEGRADED_QUANT_ALERT` (severity
  WARNING, regardless of the 0.0 confidence) instead of silently
  suppressing it the way a normal low-confidence report would be -- the
  point is the user should still learn a technical signal fired even
  with zero qualitative backing. `DEGRADED_QUANT_ALERT` participates in
  the state-transition gate above as its own pseudo-state, so a sustained
  LLM outage doesn't re-alert on every single signal for the same
  ticker.
- **`consumer.py`** — subscribes to BOTH `talonx:signals:quant` and
  `talonx:reports:brain` on one Redis connection (`pubsub.subscribe`
  called with two channel names), routes each incoming message to the
  correlator by channel, and re-runs the decision matrix after every
  single update -- so a decision can be triggered by either half of the
  pair arriving second, not just by report arrival. Same reconnect-with-
  backoff shape as `talonx_quant.consumer` / `talonx_brain.consumer`; a
  bad message on either channel is logged and dropped rather than killing
  the listener.
- **Deliberately self-contained at the code level**, same as
  `talonx_quant`: re-declares the `QuantSignal` and `ResearchReport` wire
  shapes locally rather than importing `talonx_quant`/`talonx_brain`
  Python objects (its `ResearchReport` mirror is trimmed -- it omits
  `citations`, which the decision matrix never uses; Pydantic's default
  `extra="ignore"` behavior means parsing the real, fuller wire payload
  still works fine). Its only real dependencies are `redis.asyncio`,
  `pydantic`, and `asyncio`, matching the module spec.
- **Risk guardrails implemented**: a confidence gate (`TALONX_CORE_MIN_CONFIDENCE`),
  a per-ticker time cooldown (`TALONX_CORE_TICKER_COOLDOWN`), and the
  state-transition + price-delta re-trigger gate
  (`TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT`) above. **Not implemented**: a
  global cross-ticker rate limiter -- see [../roadmap.md](../roadmap.md).
- Wired into `run_talonx.py` as a fourth continuous task (see
  [orchestrator.md](orchestrator.md)), unconditionally (unlike Module 3,
  it has no optional external dependency -- no API key, nothing that can
  plausibly be missing beyond what Modules 2/3 already require).
  `--skip-core` leaves it out on purpose. Run it standalone instead
  ([../running.md](../running.md)) if you want it decoupled.

## Long-term decision matrix

See [../phase2-multi-horizon.md](../phase2-multi-horizon.md) for
`evaluate_long_term()` — `HIGH_CONVICTION_BUY`, `HOLD_QUALITY`,
`TAKE_PROFIT_REBALANCE`, `UNDER_PERFORM_REBALANCE`.
