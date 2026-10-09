# POST_DELIVERY_ALERT_MARKOUT_V1: proposed protocol (INACTIVE; requires owner approval before activation)

**Question.** After a Telegram research opportunity was delivered, did a useful price move remain, under declared
timing and cost assumptions?

**Output name.** *Post-delivery price markout under stated cost assumptions.* It is **not** realised profit, an
executable fill or a portfolio return.

This protocol is separate from the promotion `paper_outcomes` markouts (unchanged), VR_PAPER_V1, the V2 forward
tracker and every frozen study. All values below were fixed **before any post-delivery outcome was inspected**. No
historical alert was paired with later prices while writing it.

## 1. Delivery semantics (traced in code, 2026-10-09)

**Lifecycle.**
1. `promotion.Promoter._release` → `promotion.db` row (`promotion_id`, state `PROMOTED_SIGNAL`, reason
   `RESEARCH_REVIEW_ALERT`).
2. `NotifyStore.enqueue` → outbox row `results/opportunity/promotion_signal_notifications.db`
   (`event_id = dedup_key = promotion_id`, `created_at_utc`).
3. `talonx_ops.notify.worker.drain` → `_send_sync` → `talonx_dispatch.telegram_client.TelegramClient.send`.
4. `update_outbox(state=SENT, sent=True)`.

**Identifiers.**
- Opportunity / outbox ID: `promotion_id` (= outbox `event_id`, stable and unique; one promotion per candidate
  identity).
- **Telegram `message_id`: not persisted.** `send_message()` returns a `Message` (with `message_id` and server `date`),
  but `_send_sync` discards it. `transport_ref` is the synthetic string `telegram:sent:<dedup_key>`.

**Timestamps.**

| Timestamp | Where | Survives crash / retry? |
|---|---|---|
| Market data | `promotions.data_as_of_utc` | yes |
| Promotion decision | `promotions.decision_utc` | yes |
| Outbox enqueue | `outbox.created_at_utc` | yes |
| Send start | **not persisted** | — |
| Telegram API acceptance | **not persisted** | — |
| Local persistence after acceptance | `outbox.sent_at_utc` | yes (written once, when state becomes SENT) |

**Ambiguity and duplicates.** `TelegramClient.send` is called with its default `retry_ambiguous=True`, so a timeout or
network error *after* the request left is **blind-retried inside the client**.
- A duplicate message is possible but **invisible** to the outbox: `attempts` stays 1 and no error is stored.
- Worker-level failures do show: `attempts > 1`, `last_error`, state RETRY / AMBIGUOUS / FAILED.

Observed on the 161 review alerts so far (metadata only): all SENT on attempt 1 with no errors. Outbox-creation →
`sent_at_utc` was 0.65–3.12 s (median 1.24). Data timestamp → `sent_at_utc` was 16.4–30.6 min (median 19.0).

**Delivery anchor `D` = `outbox.sent_at_utc`.** This is the *local time at which the system recorded Telegram API
acceptance*. It is **not** device receipt or user reading.
- It is conservative: never earlier than acceptance (it includes in-client retry back-off and ~1 s of persistence
  lag), so it cannot pull the entry earlier than the alert existed.
- It uses the local machine clock (not NTP-verified here); this is a stated limitation.
- No earlier timestamp (decision, enqueue, data) is ever substituted.

**Ambiguous delivery.** `attempts > 1`, a non-null `last_error`, or state `AMBIGUOUS` → `AMBIGUOUS_DELIVERY`. Such
alerts are counted and excluded from the primary statistic. In-client ambiguous retries cannot be detected; this is a
residual limitation, and persisting the Telegram `message_id`/`date` would close it (§8).

## 2. Prospective population

**Included.** Outbox rows with `event_type = RESEARCH_OPPORTUNITY`, `destination = TRADE_EVENT`, producer
`talonx_opportunity.promotion`, `state = SENT`, and **both** `created_at_utc >= A` and `sent_at_utc >= A`, where `A`
is the activation boundary (UTC, a future instant fixed in the config before activation). The joined promotion must
be `PROMOTED_SIGNAL` / `RESEARCH_REVIEW_ALERT`.

**Excluded.**
- Rows before `A` are never observations (no replay).
- Legacy `PAPER_OPPORTUNITY` rows are never observations.

**Interpretation.** Long-only (the review alert is a BULLISH setup).

**Repeat alerts.** One primary observation per `(trading window, symbol)`: the **first** delivered alert. Later alerts
for the same symbol in the same window are `REPEAT_SAME_WINDOW`, recorded and excluded. Different windows are separate
observations.

## 3. Timing (1-minute SIP bars; bar `t` = interval start; a bar covers `[t, t+60s)`)

**Reaction delay `R` = 300 s (5 minutes).** This assumes a human reviews an *unvalidated* alert (read, open a chart,
place an order) before acting. It is chosen for plausibility of human action, not from returns. A shorter value would
model an automated follower, which this product is not.

**Entry.**
- Entry time `T_e = ceil_to_minute(D + R)`. When `D + R` falls exactly on a minute, `T_e = D + R`.
- The entry bar is the **first bar with start in `[T_e, T_e + 5 min)` and volume > 0**.
- Entry price = that bar's **open**. A bar that began before `T_e` is never used.
- No such bar → `MISSING_ENTRY`. No sliding beyond 5 minutes.

**Primary horizon `H` = 30 minutes after `T_e`.**
- It matches the alert's stated INTRADAY horizon and the existing shortest promotion markout horizon.
- It is long enough to exceed the data delay, and short enough to stay inside the session for most alerts.
- There is **one** horizon only.

**Exit.**
- Exit time `T_x = T_e + 30 min`.
- The exit bar is the **last bar with start in `[T_x − 5 min, T_x − 1 min]` and volume > 0** (the last trade before
  `T_x`).
- Exit price = that bar's **close**. No such bar → `MISSING_EXIT`.

**Session (XNYS calendar via `talonx_opportunity.phases.trading_window`; half days included).**
- `D + R` at or after the regular close → `LATE_SESSION_INELIGIBLE`.
- `T_x` after the regular close (`close_utc`, which is 18:00Z on half days) → `LATE_SESSION_INELIGIBLE`.
- Delivery outside the regular session → `OUT_OF_SESSION`. Promotions are REGULAR-only, so this is expected to be 0.
- No overnight holding and no extension.

**Prices.** As-traded, `adjustment=raw`, SIP feed. Entry and exit fall in the same regular session, so corporate
actions cannot occur between them.

**Halts** are not observable. A halt appears as missing bars, so it is handled by the missing rules and counted.

## 4. Costs (stated assumption, not inherited)

**Cost (bps) = quoted NBBO spread at entry + 5 bps.**
- Spread at entry: median of `(ask − bid) / mid` over SIP quotes in `[T_e, T_e + 60 s)`, in bps of mid. This is a full
  spread, approximating crossing half the spread at entry and half at exit.
- The 5 bps allowance covers fees, routing and minimal slippage for the small notional of a single reviewer.
- It is subtracted **exactly once** from the gross markout.
- There is no market-impact model: order size and executable depth are unknown.

**No valid quotes** → the cost is unknown. The gross markout is still recorded; the cost-adjusted markout is
`COST_UNAVAILABLE` and is reported as missing.

**Why this cost and not another strategy's.** The research 20 bps (V2) and VR's `max(20 bps, spread)` belong to other
holding periods and populations. Here the alert universe is the top-600 ADV20 names (cutoff ≈ $205M per day), so the
measured spread is the direct, observable cost component.

## 5. Data, maturity, failure and restart

**Acquisition** is a separate step from measurement.
- Once a window has **matured** (regular close + 60 minutes, so SIP bars are final and past the 15-minute delay
  window), fetch 1-minute bars for `[T_e, T_x)` and quotes for `[T_e, T_e + 60 s)` per observation.
- Store the raw response with a SHA-256 hash.
- A refetch is an explicit, new, versioned run; it never silently replaces data.

**Bounded waiting.**
- An observation waits at most **2 trading sessions** after maturity for data, then becomes `MISSING_DATA_TIMEOUT`.
- There is no infinite polling. The measurement never runs during the session, never delays or gates Telegram
  delivery, and holds no production subscription.

**Observation states.**
- `WAITING_FOR_DATA`, `MATURE` (measured);
- `MISSING_ENTRY`, `MISSING_EXIT`, `MISSING_DATA_TIMEOUT`;
- `AMBIGUOUS_DELIVERY`, `REPEAT_SAME_WINDOW`, `LATE_SESSION_INELIGIBLE`, `OUT_OF_SESSION`;
- `INVALID` (for example, a source row failing validation).

**Restart.**
- Processing is idempotent: the primary key is `event_id`, and inserts are no-ops when the row already exists.
- A crashed run resumes. Measured observations are never recomputed under the same protocol version.

**Segments.** The segment key is `(protocol version, promotion policy fingerprint, DTU policy fingerprint, delivery
mode)`. Any change starts a new segment, and segments are never pooled.

## 6. Observation period and endpoint

- **Activation boundary `A`:** the start (00:00Z) of the first trading window after owner approval.
- **Observation period:** the first **20 trading sessions** from `A`.
- **Endpoint:** the report is produced once the 20th session has matured (+ 2 sessions of data wait).
- No interim profitability verdict.

## 7. Report (descriptive; no PASS threshold)

Per segment:

**Counts.**
- delivered;
- excluded by reason (ambiguous, repeat, late-session, out-of-session);
- eligible;
- measured;
- missing by reason;
- coverage = measured / eligible, with missing kept in the denominator.

**Timing.**
- distribution of `D − data_as_of` and `T_e − D`;
- entry and exit bar lags.

**Markouts (gross and cost-adjusted).**
- mean, median and fraction > 0;
- 5th and 10th percentiles, and the worst 5;
- the cost distribution.

**Concentration.**
- per-symbol and per-session counts and contributions;
- the top-5 share.

**Explicit statements.**
- These are **alert-level averages**, not portfolio performance: no capital, overlap or position limits are modelled.
- Inference is weak. Alerts in one session share market moves, so the effective sample is closer to the number of
  sessions (20) than to the number of alerts.
- A 95% interval, if shown, uses a **session-clustered bootstrap** (resampling whole sessions, 10,000 draws, seed
  fixed), labelled low-power, and is not a pass/fail test.

## 8. What it can and cannot establish

**Can establish.** Whether, on average and in this period, the price moved favourably between a fixed post-delivery
entry time and 30 minutes later, net of a stated spread-based cost, for alerts delivered by this product.

**Cannot establish.**
- executable fills or depth;
- slippage beyond the quoted spread;
- device receipt or read time;
- behaviour outside 20 sessions or other regimes;
- profitability of any trading strategy;
- the value of alerts that were ambiguous, repeated or ineligible.

**Gaps that would improve fidelity:**
1. Persist the Telegram `message_id` and server `date` from the `send_message` return value. This gives a precise
   anchor and makes duplicates detectable. It would be a small change in `talonx_ops/notify/worker.py`, **outside this
   task**.
2. Halt data (not available).
3. Executable depth (not available).
