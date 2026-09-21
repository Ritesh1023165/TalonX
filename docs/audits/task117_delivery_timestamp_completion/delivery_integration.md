# Intelligence-card delivery — completed runner integration

## Is the drain wired into the real supervised path? **YES.**

`IntelligenceService.run_poll_loop` (the supervised loop that `python -m
talonx_ingest.intelligence.service poll` runs) now calls **one bounded**
`self.deliver_cycle(now=…)` immediately after `poll_cycle` + `drain_retries`.
Its result is recorded on the per-cycle summary (`summary["delivery"]`).

`deliver_cycle`:
- uses the **existing** transport authority — `TelegramSenderAdapter` wraps
  `talonx_dispatch.telegram_client.TelegramClient`. **No second poller, no
  parallel sender loop.**
- processes `IMMEDIATE` then `DIGEST` in **separate** `process_pending` passes
  → a DIGEST card is never sent as if it were IMMEDIATE.
- is wrapped in `asyncio.wait_for(..., timeout=deliver_cards_timeout_seconds)`
  (default 20 s) per route → a slow / backing-off transport **never blocks
  source polling** (the loop logs a warning and continues).
- per-cycle cap `deliver_cards_per_cycle` (default 20) bounds burst.

## False-`SENT` states fixed

`process_pending` is now **mode-driven**, not `dry_run`-driven:

| mode | behaviour | can produce `SENT`? |
|---|---|---|
| `"disabled"` (default when neither `mode` nor `dry_run` is given, and the runner's default) | **no sender is called; NO row is mutated.** Eligible rows stay `PENDING`; the result reports `held` + `held_reason="delivery_disabled"`; a `HELD` log line is written. | **no** |
| `"simulate"` (`dry_run=True` maps here) | renders the drain **plan** (which rows, in what order) on an isolated basis; the outbox is **not touched**; nothing is represented as delivered. `simulated` + `simulated_ids`. | **no** |
| `"enabled"` | the real `TelegramSenderAdapter`. `ok` (real ack) → `SENT`. transient fail → `RETRY`. permanent → `FAILED`. **unconfirmable outcome → `AMBIGUOUS`** (durable, never blind-retried). transport not configured → `held` + `held_reason="transport_not_configured"`. | **yes — only here, only on a real ack** |

`NullSender`'s "reports success" is no longer used to mark rows: it is gone from
the drain path entirely.

## Configuration reaches the running constructor

`ServiceConfig` (from `ServiceConfig.from_env()` in `service.py`):

| field | env | default | meaning |
|---|---|---|---|
| `deliver_intelligence_cards` | `TALONX_INTEL_DELIVER_CARDS` | **`False`** | the explicit enablement. `False` → `deliver_cycle` runs in `"disabled"` mode. |
| `dry_run_delivery` | `TALONX_INTEL_DRY_RUN_DELIVERY` | `True` | must ALSO be `False` for the enabled path (`--send` on the CLI sets it). |
| `deliver_cards_per_cycle` | `TALONX_INTEL_DELIVER_PER_CYCLE` | 20 | rate cap |
| `deliver_cards_enforce_age_cutoff` | `TALONX_INTEL_DELIVER_AGE_CUTOFF` | `True` | D5 age cutoff on the enabled path |
| `deliver_cards_timeout_seconds` | `TALONX_INTEL_DELIVER_TIMEOUT_SECONDS` | 20.0 | per-route hard timeout |

Enabled path = `deliver_intelligence_cards=True` **and** `dry_run_delivery=False`
**and** the Telegram client `is_configured`.

## Acceptance (task §2) — verified by `tests/test_task117_delivery_runner_integration.py`

| criterion | test |
|---|---|
| config reaches the running service constructor | `_svc(tmp, deliver_intelligence_cards=True, dry_run_delivery=False)` → `deliver_cycle` mode `"enabled"` |
| eligible new IMMEDIATE cards reach the final transport boundary | `test_disabled_by_default_holds_then_enable_sends_after_restart` — `inter2.sent == [did]` |
| DIGEST not treated as IMMEDIATE | `test_digest_not_treated_as_immediate` — separate `IMMEDIATE`/`DIGEST` result blocks; routes preserved |
| backoff does not block source polling | `deliver_cycle` `asyncio.wait_for` per route (unit: `deliver_cards_timeout_seconds`; the loop catches `TimeoutError`) |
| restart preserves pending delivery | `test_disabled_by_default_...` — a disabled cycle leaves the row PENDING; a fresh `IntelligenceService` on the same ledger then delivers **the same row** |
| permanent + ambiguous do not produce retry storms | `test_ambiguous_send_is_durable_and_not_retried` — row → `AMBIGUOUS`, a 2nd cycle does **not** re-attempt; `TelegramSenderAdapter` maps `invalid`/`forbidden`/`chat not found` → `permanent` (FAILED, no retry) |
| duplicate events / overlap with the Original long-term route | `enqueue` dedups on `delivery_id = channel:card_id:render_version`; `update_policy` gates re-opens; the Original long-term route (`talonx:alerts:longterm` → `talonx_dispatch`) is a **different channel + consumer** and is untouched — the two are documented as distinct in `README`/`corrected_three_day_reconciliation.md` |
| informational cards never become BUY/SELL | `delivery/claim_safety.assert_clean` raises `PredictiveLanguageError` at render (AST-tested, pre-existing) |
| no duplicate Telegram poller / no boundary bypass | one `TelegramSenderAdapter` per cycle, wrapping the shared `TelegramClient`; no `get_updates` loop added |

## Default posture after this change

`deliver_intelligence_cards=False` → every poll cycle the drain runs in
**disabled** mode: it lists eligible rows as `held` (PENDING, reason recorded),
sends nothing, mutates nothing. Flipping `TALONX_INTEL_DELIVER_CARDS=1` +
`--send` is the production activation step (`deployment_candidate.md`), **not
performed here**.
