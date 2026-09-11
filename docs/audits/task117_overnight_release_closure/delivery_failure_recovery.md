# Delivery failure & recovery — Intelligence card delivery (Task 117 §1)

Scope: `talonx_ingest/intelligence/delivery/{outbox.py,pipeline.py}`,
`talonx_dispatch/telegram_client.py`, `talonx_ingest/intelligence/service/runner.py`.
Durable state table `intelligence_delivery`; audit table `intelligence_delivery_log`.

## State model

```
PENDING ──claim_for_send(attempt_id)──▶ IN_FLIGHT ──ack──▶ SENT (terminal)
   ▲                                        │
   │ release_claim (clean transient)        ├─ ambiguous / timeout / cancel ─▶ AMBIGUOUS (terminal, NOT retried)
   │                                        └─ clean transport reject ───────▶ FAILED / back to PENDING w/ next_retry_at
   └── mark_failed(retry) ───────────────────
PENDING ──expire_stale(now)──▶ EXPIRED (terminal, audit-logged, never deleted, never SENT)
```

New columns (additive `ALTER TABLE`, idempotent): `attempt_id`,
`in_flight_since_utc`, `transport_message_id`.

## §1A — mode validated before anything

`process_pending` / `process_digest` first line after arg-norm:
`if mode not in {"enabled","disabled","simulate"}: raise InvalidDeliveryMode`.
This is **before** `recover_in_flight`, before `expire_stale`, before
`outbox.pending`, before any sender call. `dry_run=True` maps to `simulate`.
Only `enabled` can produce `SENT`, and only on a real ack.
Test: `test_invalid_mode_fails_closed_before_any_mutation` (row stays PENDING,
`sender.calls == []`).

## §1B — persist-before-network, single claim, restart-safe

- `claim_for_send(delivery_id, attempt_id, now)` (outbox.py:389) issues
  `UPDATE … SET state='IN_FLIGHT', attempt_id=?, in_flight_since_utc=?
   WHERE delivery_id=? AND state='PENDING' AND (next_retry_at_utc IS NULL OR next_retry_at_utc<=?)`
  then **commits**, and returns `rowcount == 1`. The commit happens before
  `sender.send(row)` runs — proven by `test_claim_is_persisted_before_the_network`
  (the sender re-reads the row and sees `IN_FLIGHT` + an `attempt_id`; the
  `IN_FLIGHT` audit line precedes the `SENT` line).
- **Competing drainer:** the `WHERE state='PENDING'` predicate is atomic in
  SQLite; a second drainer's `claim_for_send` returns `False` and it does not
  send. `test_competing_drainer_cannot_send_a_claimed_row`.
- **Restart with an in-flight attempt:** `recover_in_flight(now, stale_after_seconds=90)`
  (outbox.py:423) moves rows whose `in_flight_since_utc <= now-90s` to
  `AMBIGUOUS` with reason *"recovered from a stale IN_FLIGHT claim — outcome
  unknown, not retried"*. It runs at the top of every `process_pending` /
  `process_digest` call (all modes). `test_restart_recovers_a_stale_in_flight_row_to_ambiguous`.
- **No blind retry in the transport layer:** `TelegramClient.send(…,
  retry_ambiguous=False)` raises `TelegramAmbiguousError` immediately on
  `TimedOut` / `NetworkError` instead of retrying. `RetryAfter` / HTTP 429 is a
  *clean Telegram rejection* and stays retryable. `test_lower_layer_does_not_blind_retry_an_ambiguous_timeout`.
- **Not claimed:** network-level exactly-once. The guarantee is *durable,
  single-claim, restart-safe, with a visible AMBIGUOUS terminal* for outcomes
  Telegram may or may not have accepted.

## §1C — accurate terminal state

| outcome | state | recorded |
|---|---|---|
| real ack | `SENT` | `transport_message_id` = the Telegram `Message.message_id` where the API returns it; digest → `digest:<digest_id>:<message_id>` |
| disabled mode | stays `PENDING` | `held_reason='delivery_disabled'` + `HELD` audit line; sendable after enablement |
| simulate / `dry_run` | unchanged | drain **plan** only; outbox not mutated, transport not called |
| clean transient reject | `PENDING` w/ `next_retry_at_utc` (backoff), `attempts++` | `RETRY` audit line |
| permanent reject (`invalid` / `forbidden` / `chat not found` / `bad request`) | `FAILED` | `permanent=True` on the `SenderResult` |
| timeout / network / cancel / unexpected exception | `AMBIGUOUS` | reason string; row id in `DrainResult.ambiguous_ids` |

Audit-log writes (`intelligence_delivery_log`) are a **separate** statement from
the delivery-state `UPDATE`; a failed log insert does not roll back a committed
state transition and vice-versa. Tests:
`test_sent_records_message_id_disabled_holds_simulate_no_sent`,
`test_permanent_vs_transient_stay_distinguishable`.

## §1D — decision time is the real time

`process_pending` sets `now = datetime.now(timezone.utc)` when the caller does
not pin it, and each enabled row captures its own `send_now = datetime.now(utc)`
just before the claim. Expiry, retry-eligibility (`next_retry_at_utc <= now`)
and the send timestamp all use that value, never a timestamp captured before the
poll. `runner.deliver_cycle` computes its own drain-time `now` (it does **not**
reuse `poll_cycle`'s). `test_decision_uses_the_actual_send_time`.

## §1E — bounded, visible, non-swallowing

`runner.deliver_cycle`:
- each route (`process_pending` IMMEDIATE, `process_digest` DIGEST) is wrapped
  in `asyncio.wait_for(..., timeout=self.config.deliver_cards_timeout_seconds)`
  (default 20 s) so a stuck send cannot block source polling;
- `asyncio.CancelledError` is re-raised (cooperative shutdown, no swallow);
- `asyncio.TimeoutError` → `summary["timed_out"]=True; summary["ok"]=False`;
- any other `Exception` → `logger.error(...)` + `summary["error"]=repr(exc)` +
  `summary["ok"]=False`; it is **not** folded into a healthy poll result.
- `DrainResult.errors` carries per-row unexpected-exception strings and sets
  `summary["ok"]=False`.

`test_unexpected_sender_error_is_visible_not_swallowed`,
`test_cancellation_mid_send_marks_ambiguous_and_propagates`.

## Runner enablement gate

`enabled = bool(config.deliver_intelligence_cards) and not config.dry_run_delivery`.
Both default safe (`False`, `True`). When not enabled the runner uses
`_InertSender` (configured=False, `send` raises) so a disabled cycle can never
touch a transport. Env: `TALONX_INTEL_DELIVER_CARDS`,
`TALONX_INTEL_DRY_RUN_DELIVERY`, `TALONX_INTEL_DELIVER_PER_CYCLE`,
`TALONX_INTEL_DELIVER_TIMEOUT_SECONDS`,
`TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS`, `TALONX_INTEL_DELIVER_AGE_CUTOFF`.
