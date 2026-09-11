# Task 77I Stage 2 — Alert Delivery Contract

## Classification (`notification_outbox.py::classify`)

| Decision | Classification | Notified? |
|---|---|---|
| `recommendation == BUY` | `ACTIONABLE_BUY` | Yes |
| `recommendation == SELL_TO_CLOSE` | `ACTIONABLE_SELL` | Yes |
| `NO_TRADE`, reason `STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION` | `WATCH_OBSERVATION_ONLY` | Yes (never promoted to a BUY) |
| `HOLD` | — | No |
| `NO_TRADE` (bearish/neutral, or data-insufficient) | — | No |

`WATCH_OBSERVATION_ONLY` exists specifically for the (today, the ONLY REAL) case a bullish,
otherwise-eligible setup is blocked purely by unvalidated strategy status — genuinely useful
operator visibility ("the strategy would have entered here") without ever letting that
visibility masquerade as an actionable BUY. `HOLD` and non-actionable `NO_TRADE` are
deliberately silent — with the strategy currently ALWAYS unvalidated, decide() resolves to
`NO_TRADE`/`STRATEGY_UNVALIDATED_...` on literally every bullish tick a real approved strategy
would have bought; without the WATCH/silent split, this would spam an alert on every single such
tick.

## Deduplication

Key = `stable_id("notif", ticker, trading_date_et, classification, recommendation,
sorted(reason_codes))` — deliberately excludes `decision_id`/`timestamp`, so repeated identical
evaluations across many ticks (e.g. "still bullish but unvalidated" on every bar) collapse into
exactly ONE queued notification per distinct `(ticker, date, classification)` combination for
the whole trading day, not one per tick.

## Delivery semantics — honesty over false certainty

- **Record before dispatch**: `enqueue()` (called synchronously inside
  `DecisionEngine._record_decision`, itself called before the real `order_intent` attempt) is
  the durable write; `dispatch_pending()` (called independently, once per `SessionRunner` tick)
  is the ONLY thing that ever calls the adapter.
- **Bounded retries**: `max_attempts = 3`. Attempt count and `PENDING`/`RETRY`/`SENT`/`FAILED`/
  `UNCERTAIN` status persist across restart (full-file JSON, same pattern as `LifecycleState`).
- **Delivered only means delivered**: `status = "SENT"` only when the adapter (a bare
  `Callable[[str], bool]`, the SAME interface `talonx_piv.telegram.sender` already implements)
  explicitly returns `True`. `False` -> `RETRY` (or `FAILED` once attempts are exhausted). An
  adapter exception -> `UNCERTAIN`, never silently treated as either sent or failed — the true
  delivery state genuinely is unknown, and the record says so.
- **No adapter configured** (no Telegram token/chat id — `sender(...)` itself already handles
  this by returning `False`; the outbox additionally treats a bare `None` adapter, used by every
  pre-existing test-construction default, as an immediate, honestly-recorded `FAILED` rather
  than a fabricated `SENT`).
- **This codebase never claims exactly-once external delivery** — Telegram's own API offers no
  such guarantee, and this outbox does not pretend otherwise; "SENT" means "the adapter
  acknowledged success," not "the operator's phone definitely showed this message."

## Independence (the core Stage 0 requirement)

`dispatch_pending()` is called from `SessionRunner._dispatch_pending_notifications` —
INDEPENDENTLY of the decision path, wrapped in its own try/except so a bug or outage there can
never crash the tick loop. `enqueue()` itself never calls the adapter. Both are proven, at the
`DecisionEngine` integration level (not just the `NotificationOutbox` unit level), by
`tests/test_task77i_alert_shadow_independence.py`.

## Reused, not reinvented

The send adapter is the EXACT existing `talonx_piv.telegram.sender(token, chat_id)` factory —
production code gains a second, independent CALLER of this factory, never a second Telegram
integration. `telegram.py` itself has zero diff.
