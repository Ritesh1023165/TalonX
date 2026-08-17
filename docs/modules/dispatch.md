# `talonx_dispatch` — Module 5: Notification Dispatcher & Streamlit Interface

```
talonx:alerts:dispatch (Redis)
    → parse + validate each message as ActionableAlert
    → record it to the audit trail FIRST, unconditionally (store.py --
      SQLite, durable; this is now the ONLY durable historical record of
      alerts anywhere in the pipeline, since Redis Pub/Sub itself isn't one)
    → if Telegram is configured AND severity >= TALONX_DISPATCH_MIN_SEVERITY:
        → Smart Dispatch Filtering (consumer.py's _evaluate_push_eligibility):
            - action not in the eligible set (CONFIRMED_BULLISH/BEARISH,
              or long-term HIGH_CONVICTION_BUY/TAKE_PROFIT_REBALANCE/
              UNDER_PERFORM_REBALANCE) → suppressed, ACTION_MUTED
            - research_confidence < TALONX_DISPATCH_MIN_CONFIDENCE (intraday
              only) → suppressed, CONFIDENCE_BELOW_GATE
            - this ticker pushed within the last TALONX_DISPATCH_PUSH_
              COOLDOWN_MINUTES (default 45) AND price hasn't moved >=
              TALONX_DISPATCH_RETRIGGER_PRICE_DELTA_PCT (default 1.0%) since
              → suppressed, PRICE_DELTA_TOO_LOW (or PUSH_COOLDOWN_ACTIVE if
              there's no comparable prior price at all)
            - a suppressed alert is marked on its OWN audit row
              (suppress_reason) -- still 100% recorded, never pushed
        → format a SHORT summary (ticker/action/price/confidence/one-line
          quant trigger + this alert's ID -- formatter.format_telegram_summary)
        → send via python-telegram-bot, with retry/backoff (telegram_client.py)
        → record delivery success/failure back onto that alert's audit row

(concurrently, in the SAME process -- DispatchAgent.run() is 3 tasks, not 1:)
Telegram (incoming messages, telegram_listener.py's TelegramReplyListener)
    → long-polls Bot.get_updates() -- Telegram's own server-side long-poll,
      not a busy loop
    → someone replies to a push with its ID (or "/details 47", "/id 47")
    → look it up (store.get_by_id) → reply with the FULL writeup, now
      including a technical-indicator section (RSI/MACD/volume surge, 15m
      200-SMA trend status, ATR stop/target -- formatter.format_telegram_details);
      not found (or purged by retention) → a "not found" reply
    → "/ping" or "ping" → an Interactive System Health Check reply:
      uptime, CPU/RAM, the ingest WebSocket's heartbeat status, and
      today's signal counts from the audit trail (see "Interactive
      health check" below) -- anything else → a usage hint

(concurrently, ALSO subscribed -- talonx:quant:rejected)
    → parse + validate each message as RejectedCandidateEvent
    → record it to store.py's rejected_candidates table -- ONE row per
      candidate a talonx_quant gate dropped (trend_gate, rr_gate,
      confluence_gate, etc.), never pushed/shown in the main feed, purely
      a durable audit trail for "why didn't this fire" -- see Rejection
      Trace Logging below
    → only ever responds to the configured TELEGRAM_CHAT_ID -- a personal,
      single-user bot, not multi-tenant

(also concurrently:) retention sweep -- purge_older_than(), once at
startup then every TALONX_DISPATCH_RETENTION_SWEEP_HOURS (default 24h),
deleting audit rows older than TALONX_DISPATCH_RETENTION_DAYS (default 5)
so a long-running install doesn't grow dispatch_audit.db forever (and so
an alert ID stops being answerable via Telegram once it's aged out)

(independently, as a SEPARATE process:)
Streamlit (`streamlit run talonx_dispatch/app.py`)
    → reads the SAME audit trail SQLite file
    → renders live metrics, a derived per-ticker watchlist, a live alert
      feed, a filterable audit trail table, and a Daily Funnel & Metrics
      tab (Stage-Gate Metric Funnel counters read from Redis -- see below)
    → auto-refreshes on a timer (streamlit-autorefresh) for a "live" feel
```

- **Two cooperating processes, not one -- a deliberate architecture
  decision, not what the module spec's file list literally implies.**
  Streamlit reruns its entire script top-to-bottom on every
  interaction/refresh, which is fundamentally incompatible with holding
  a persistent asyncio Redis Pub/Sub subscription open. So `consumer.py`
  (the async Redis subscriber + Telegram dispatcher) and `app.py` (the
  Streamlit dashboard) are separate, independently-run processes that
  communicate through `store.py`'s SQLite file rather than sharing
  in-process state -- same "async producer writes to durable local
  SQLite, something else reads it" shape as `talonx_core.store`. Both
  need to be running for the dashboard to show anything
  ([../running.md](../running.md)).
- **`store.py`** — the audit trail itself, and the first durable
  historical record of alerts in the whole pipeline (talonx_core's own
  `TickerStateStore` persists correlator *state*, not a log of *published
  alerts*). SQLite, same pattern as `talonx_ingest.storage.ledger` /
  `talonx_core.store`, with one deliberate deviation: `check_same_thread`
  defaults to `True` (matching the others) for `consumer.py`'s single-
  process, single-thread connection, but `app.py` explicitly passes
  `check_same_thread=False` for its own connection, since Streamlit's
  execution model can run a cached session object on a different thread
  than the one that created it -- a real constraint the ledger/core_state
  precedent didn't have to deal with. WAL journal mode is enabled for
  smoother concurrent read-while-write between the two processes. Every
  public method holds an internal `threading.Lock`, added after a real
  concurrency bug: two Streamlit reruns sharing the cached, `check_same_
  thread=False` connection on different threads could interleave and hit
  an "impossible" state. `get_by_id()` backs the Telegram reply lookup;
  `purge_older_than()` backs the retention sweep
  (`TALONX_DISPATCH_RETENTION_DAYS`, default 5); `count_alerts_today()`
  backs the `/ping` health check's signal counts.
- **Smart Dispatch Filtering** (`consumer.py`, `store.py`'s `suppress_reason`
  column) — added after a live session logged 86 Telegram pushes in 4.3
  hours (~20/hour): 44.8% were non-actionable `CONTRADICTED` alerts, and
  40.2% were the same ticker re-alerting every ~20 minutes on minor price
  noise. `_evaluate_push_eligibility()` is a pure, directly-unit-testable
  function applying 3 independent gates, cheapest/stateless first, BEFORE
  a Telegram send is even attempted — **unconditional audit persistence is
  untouched**: `record_alert()`/`record_long_term_alert()` still write
  every alert before this filtering decision is made, so the audit trail
  and Streamlit dashboard always show 100% of what `talonx_core` published.
    1. **Action eligibility** (`TALONX_DISPATCH_MUTE_CONTRADICTIONS`,
       default `true`) — an ALLOWLIST, not just a `CONTRADICTED`-specific
       check: only actions representing a genuine trade decision
       (`CONFIRMED_BULLISH`/`CONFIRMED_BEARISH` intraday;
       `HIGH_CONVICTION_BUY`/`TAKE_PROFIT_REBALANCE`/
       `UNDER_PERFORM_REBALANCE` long-term) are push-eligible. Everything
       else — `CONTRADICTED`, `DEGRADED_QUANT_ALERT`, long-term
       `HOLD_QUALITY` — is a "no strong trade signal" state and gets
       muted the same way (`suppress_reason = "ACTION_MUTED"`).
    2. **Research confidence gate** (`TALONX_DISPATCH_MIN_CONFIDENCE`,
       default `0.75`) — intraday only. `LongTermActionableAlert` has no
       `research_confidence` field; its own `quality_score >= 7`
       threshold is already enforced upstream in `talonx_core`'s
       long-term decision matrix before a long-term alert is even
       published, so a redundant proxy gate isn't added here
       (`suppress_reason = "CONFIDENCE_BELOW_GATE"`).
    3. **Per-ticker push cooldown with a price-delta re-trigger bypass**
       (`TALONX_DISPATCH_PUSH_COOLDOWN_MINUTES` default 45,
       `TALONX_DISPATCH_RETRIGGER_PRICE_DELTA_PCT` default 1.0) — a
       SEPARATE, longer lockout on the PUSH itself, on top of whatever
       cooldown `talonx_core` already applied before publishing the
       alert at all. Tracked as a plain in-process dict keyed by ticker
       (`DispatchAgent._last_telegram_push` / `_last_telegram_push_long_term`
       — kept separate per horizon so a `DUAL_HORIZON` ticker's two
       cadences can't clobber each other), not Redis — unlike
       `talonx_quant`'s loss-lockout, no OTHER process needs to see this
       state, so a Redis round-trip would be pure overhead; resets on
       restart, matching `talonx_core`'s own in-memory per-ticker
       cooldown. If a new alert arrives inside the cooldown window,
       price is compared against the last PUSHED price: a move
       >= the retrigger threshold bypasses the cooldown
       (`suppress_reason` stays unset, a genuine push goes out); under
       threshold suppresses with `suppress_reason = "PRICE_DELTA_TOO_LOW"`
       (the more specific diagnostic — the delta WAS checked); the rare
       case of no comparable prior price at all falls back to the
       generic `"PUSH_COOLDOWN_ACTIVE"`. Only a SUCCESSFUL push updates
       the reference (timestamp, price) — a suppressed candidate never
       counts as one.

  A fully sent/attempted alert's `suppress_reason` reads the literal
  string `"NONE"` (not SQL `NULL`) — `NULL` is reserved for a row from
  before a push decision was ever made (or, after a schema migration, a
  pre-existing row from before this column existed at all).
- **Rejection Trace Logging** (`consumer.py`'s `_handle_rejected_candidate`,
  `store.py`'s `rejected_candidates` table,
  `TALONX_REDIS_REJECTED_CANDIDATES_CHANNEL` default `talonx:quant:rejected`)
  — a genuinely different gap than Smart Dispatch Filtering above:
  Smart Dispatch Filtering's `suppress_reason` only ever covers an alert
  that already made it all the way to `talonx:alerts:dispatch` (i.e. quant
  AND research both fired and were correlated). A candidate `talonx_quant`
  drops upstream — failed confluence, structural R:R, trend, ATR-move/
  volatility, an entry blackout, cooldown, loss-lockout, batch throttle,
  or a pre-market liquidity/news-catalyst gate — never reached this
  module at all before this feature, so there was no durable record of
  *why* a candidate never became a signal in the first place, only
  aggregated daily counters in `talonx_quant`'s OWN local `quant.db`
  (`QuantStateStore.suppression_counts`, still used for its EOD report).
  `talonx_quant.consumer.QuantScanner._record_rejection` now publishes
  one `RejectedCandidateEvent` PER DROPPED CANDIDATE to this channel,
  independent of and in addition to that local counter; this module
  subscribes purely to persist a durable, per-candidate row (ticker,
  `gate` — a stable identifier like `trend_gate`/`rr_gate`, see
  `talonx_quant.consumer`'s `_GATE_NAMES` — human-readable `reason`,
  signal_type/direction/price/confluence_score/risk_reward_ratio/session
  when available, `rejected_at`) to `AuditStore.record_rejected_candidate`.
  Not pushed to Telegram or shown in the main alert feed — this is an
  audit/debug trail, queryable via `recent_rejected_candidates()`/
  `rejected_candidates_for_ticker()`/`rejected_candidates_between()`, not
  an actionable notification. Swept by the same retention job as
  `alerts`/`long_term_alerts` (`purge_rejected_candidates_older_than`,
  `TALONX_DISPATCH_RETENTION_DAYS`).
- **`formatter.py`** — TWO pure formatting functions, no I/O, trivially
  unit-testable without a bot token. `format_telegram_summary(alert,
  alert_id)` is the actual push: short enough to read at a glance during
  a live session (ticker/action/price/confidence/one-line quant trigger +
  the ID), which replaced a much longer message that used to carry the
  full research writeup on every single push. `format_telegram_details(row)`
  is that full writeup — rationale, key findings, risks, model/timestamp
  footer, and (Phase 2) a technical-indicator section (RSI/MACD-cross/
  volume-surge, the 15m-200-SMA trend status, ATR-anchored stop/target) —
  sent back on demand when someone replies with the ID. It takes an audit
  ROW DICT (`AuditStore.get_by_id()`'s shape), not a live
  `ActionableAlert` -- by reply time, possibly minutes or days later, the
  original in-memory object is long gone, but every field it needs
  (including the technical ones, now persisted on the `alerts` table) is
  already a stored column. Both use Telegram's LEGACY "Markdown" parse
  mode rather than "MarkdownV2" -- MarkdownV2 requires escaping a long
  list of characters that routinely show up in Gemini-generated research
  text (`_*[]()~`>#+-=|{}.!`), which would be a much larger surface for a
  garbled message than this is worth. Legacy mode only needs 4 characters
  escaped (`_*\`[`), handled for any upstream-generated text (ticker/enum
  values are from our own schemas and never need escaping).
- **`telegram_client.py`** — the SEND side. `is_configured` gates
  everything, same "additive, degrade gracefully" pattern `RedditClient`
  established: if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` aren't set,
  `send()` is a silent no-op and the audit trail (and Streamlit
  dashboard) work normally without it. Retries transient failures with
  jittered backoff; respects Telegram's own `RetryAfter` hint exactly
  when it's given one rather than guessing a backoff; fails fast (no
  retry) on a bad token/forbidden chat, since retrying a config problem
  just burns the retry budget for nothing.
- **`telegram_listener.py`** — the RECEIVE side (`TelegramReplyListener`):
  long-polls `Bot.get_updates()` for incoming messages, and answers both
  "reply with an alert's ID" requests (looking it up in the audit trail
  and sending back `format_telegram_details`) and `/ping`. Drains any
  backlog on startup (one throwaway `get_updates()` call with no offset)
  so a restart doesn't replay old commands. Only started (as a third task
  under `DispatchAgent.run()`) if Telegram is configured -- no token,
  nothing to poll. **Only one process may poll a given bot token's
  `get_updates()` at a time** -- running two `DispatchAgent`s against the
  same `TELEGRAM_BOT_TOKEN` makes the second one's polling fail with HTTP
  409 Conflict.
- **Interactive health check (`/ping`)** — replies within the same
  long-poll turn that received the message, well under the spec's <1s
  target:
  ```
  🏓 Pong! TalonX Engine Online
  ──────────────────────────────
  🟢 Server Status: Active / Healthy
  ⏱️ Uptime: 14h 22m
  💻 CPU Usage: 4.2%  |  RAM: 1.1 GB / 8.0 GB
  📡 WebSocket Stream: Connected (Polygon.io)
  📊 Today's Signals Pushed: 12 Pushes (86 Logs)
  ```
  Uptime comes from `DispatchAgent.started_at` (process start, passed
  into the listener at construction). CPU/RAM via `psutil`. WebSocket
  status reads the `talonx:ingest:ws_heartbeat` Redis key (a plain
  `SET ... EX`, not Pub/Sub) that `talonx_ingest.market_data.run`'s
  `on_event` callback refreshes on every market event — a missing/expired
  key reads as "Disconnected." Signal counts come from
  `AuditStore.count_alerts_today()` (total rows vs. `telegram_sent=1`
  rows, summed across `alerts` and `long_term_alerts`, for the current
  UTC calendar day).
- **Stage-Gate Metric Funnel** — every module writes atomic, per-UTC-day
  Redis counters at `metrics:{YYYY-MM-DD}:{stage}:{counter}` (e.g.
  `metrics:2026-08-14:quant:published`), each module re-declaring its own
  small `_incr_metric` helper (same "no shared internal library between
  modules" convention as everything else). Dispatch's own counters:
  `received`, `muted_contradictions`, `muted_cooldown`, `muted_confidence`,
  `pushed_telegram`. The Streamlit dashboard's **"📊 Daily Funnel &
  Metrics"** tab reads these back (`app.py`'s `get_redis_client`, a plain
  sync `redis.Redis`, unlike every producer's `redis.asyncio`), renders a
  5-stage conversion chart (Bars Ingested → Quant Triggers → LLM Evaluated
  → Core Alerts → Telegram Pushes) plus a full per-module/per-counter
  breakdown table for a selected date.
- **Paper trade execution pushes** (`consumer.py`'s
  `_handle_trade_execution`, subscribed to `talonx:paper:trades`) — a
  SEPARATE, decoupled short Telegram push per executed `PaperTradeExecution`
  (BUY/SELL fill), independent of the triggering alert's own push (see
  [paper.md](paper.md)). No audit-DB record for a normal fill (Telegram
  send-or-skip only) — **except** `EOD_FLAT_LIQUIDATION` (`talonx_paper`'s
  daily 15:50 ET flatten sweep, see [paper.md](paper.md)): that one
  specific `triggering_action` is muted (no Telegram push at all, same
  "quiet but recorded" posture `ACTION_MUTED` alerts get above) and
  instead recorded to a new `paper_trade_notifications` audit table
  (`trade_id`, `ticker`, `order_type`, `triggering_action`,
  `telegram_sent`, `suppress_reason="EOD_LIQUIDATION_ROUTINE"`,
  `timestamp`) — a routine daily liquidation isn't actionable, but a user
  might still reasonably ask "why wasn't I told about this," so it's kept
  durable in its own narrower table rather than silently dropped (an
  `EOD_FLAT_LIQUIDATION` execution has no originating `ActionableAlert`
  to record it against in the `alerts` table at all).
- **Mobile push notifications are severity-gated**
  (`TALONX_DISPATCH_MIN_SEVERITY`, default `warning`) -- an `INFO`-level
  alert still gets recorded to the audit trail and shows in the Streamlit
  feed, it just doesn't buzz your phone. This is a product judgment call
  (mobile notification fatigue is real), not a technical constraint;
  lower it to `info` in `.env` if you want everything pushed.
- **Deliberately self-contained at the code level**, same as
  `talonx_quant`/`talonx_core`: re-declares a mirror of `ActionableAlert`
  rather than importing `talonx_core` Python objects — the embedded
  triggering-signal reference (`TriggeringSignalRef`) now DOES carry the
  technical-indicator fields (rsi/macd/atr/stop_price/target_price/
  trend_aligned/htf_sma_200/session), since the detail reply needs to
  display them; `sma_fast`/`sma_slow`/`volume` remain genuinely trimmed
  (never displayed). Pydantic's default `extra="ignore"` behavior means
  parsing the real, fuller wire payload still works fine. Dependencies
  match the module spec plus `psutil` (for `/ping`): `redis.asyncio`,
  `pydantic`, `python-telegram-bot`, `streamlit`, `streamlit-autorefresh`,
  `pandas`, `altair`, `psutil`.
- **`consumer.py` is wired into `run_talonx.py`** (see
  [orchestrator.md](orchestrator.md)) -- no required API key, same "safe
  to always include" reasoning as Module 4. `app.py` (Streamlit) is NOT,
  and never will be: Streamlit's own dev server is not an
  `asyncio.gather()`-compatible task (see the "Two cooperating
  processes" note above) -- always run it separately, alongside
  `run_talonx.py`, in its own terminal ([../running.md](../running.md)).

## Long-term (fundamentals) path

See [../phase2-multi-horizon.md](../phase2-multi-horizon.md) and
[../earnings-radar.md](../earnings-radar.md) for the separate
`long_term_alerts` audit table, the `#LT12`-prefixed alert IDs, and the
Event-Driven Earnings Radar's T-48h heads-up / post-earnings push
formats.
