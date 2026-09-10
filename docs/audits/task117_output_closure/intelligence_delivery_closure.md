# D5 — Intelligence delivery through the official route: closure design + backlog policy

## The actual enqueue path (traced)

```
poller.poll_once / backfill
  -> ingest_symbol_filings -> text_events         (event stored)
  -> significance.evaluate -> event_significance   (band assigned)
  -> service/enrichment.py::enqueue_card
       -> delivery/pipeline.py::render_card  (claim-safety enforced: no BUY/target/direction)
       -> delivery/outbox.py::enqueue -> intelligence_delivery row, state=PENDING
```

`service/enrichment.py` docstring: *"-> 96F durable delivery outbox row (enqueue only; no
external send)"*.

## Why nothing is delivered (root cause)

- **The delivery drain (`delivery/pipeline.py::process_pending`) is never called by the running
  service.** `runner.py::run_poll_loop` calls `poll_cycle` + `drain_retries` — where
  `drain_retries` is the **event-processing retry** drain, **not** the delivery outbox. There is
  no `process_pending` in the loop.
- `service/config.py` default `dry_run_delivery = True` (env `TALONX_INTEL_DRY_RUN_DELIVERY`);
  the top-level `service.py` overrides it to `False`, but with no drain call that is moot.
- Net: `intelligence_delivery` fills and never empties. Preserved: **9,843 rows, 100 % PENDING,
  0 ever SENT**, `intelligence_delivery_log` today shows only `ENQUEUE` events.

This is a **missing integration**, not a strictness choice, and it is **distinct from** the
Original long-term route (`talonx:alerts:longterm` → `talonx_dispatch.consumer`) which delivered
the ORCL LT6/LT7/LT8 alerts. Both must stay distinguishable.

## Implemented in this task (tested, HOLD-safe, not activated)

The pieces that make a safe drain possible were built and tested; the drain is **not wired into
the running service** here (that touches the supervised loop and needs its own validation).

| piece | file | behaviour |
|---|---|---|
| `STATE_EXPIRED` + `DeliveryOutbox.expire_stale()` | `delivery/outbox.py` | moves a PENDING row older than its per-route cutoff to `EXPIRED` — a terminal, **audit-preserving** state (an `EXPIRED` log entry; never deleted, never marked SENT). Idempotent. |
| `CARD_MAX_AGE_SECONDS` | `delivery/config.py` | `IMMEDIATE = 6 h`, `DIGEST = 24 h`. **User-facing meaning:** an IMMEDIATE HIGH/CRITICAL card not delivered within 6 h of the filing's acceptance is dropped, not sent late as if fresh; a DIGEST card has a one-trading-day window. |
| `process_pending(enforce_age_cutoff=True, max_age_seconds=…)` | `delivery/pipeline.py` | expires stale rows **before** any send. Default `enforce_age_cutoff=False` so existing callers/tests are unchanged; the runner/activation path passes `True`. `DrainResult` gains `expired` / `expired_ids`. |
| tests | `tests/test_task117_intel_delivery_age_cutoff.py` | a 6-day-old backlog row → `EXPIRED`, 0 sent, `snd.sent == []` ("NOT flooded"); a fresh row still delivers alongside; 6 h IMMEDIATE boundary; idempotency; default drain unchanged without opt-in. |

## Acceptance criteria (task §4) — how each is met or deferred

| criterion | status |
|---|---|
| newly eligible card traverses the deployed service path to an intercepted final Telegram boundary | **partially** — the drain + `TelegramSender` + intercepted `RecordingSender` are tested end-to-end in `test_delivery_pipeline.py`; **wiring into the live `runner` loop is the non-executed activation step below** |
| IMMEDIATE and DIGEST policies respected | tested (`process_pending(route=…)`, per-route age cutoff) |
| restart preserves pending work | tested (`test_restart_between_enqueue_and_send_loses_nothing`) — state lives in the outbox |
| retries / permanent failure / ambiguous have honest states | `mark_failed` (RETRY vs FAILED at `MAX_SEND_ATTEMPTS`), `permanent` flag; AMBIGUOUS is a `SenderResult` shape the transport can return |
| duplicate events / cross-route overlap don't repeat | `enqueue` dedups on `delivery_id = channel:card_id:render_version`; `update_policy` gates re-opens |
| informational significance not presented as a BUY | `claim_safety.py` `PredictiveLanguageError` — enforced at render, AST-tested |
| no duplicate Telegram poller / no boundary bypass | delivery uses the same `talonx_dispatch.telegram_client.TelegramClient`; no new poller; D2 fixes the owner count |

## Backlog policy (9,843 rows) — inspected on the isolated copy, NOT mutated

From `ingestion_ledger.db.postclose`:

| bucket | count | disposition under the policy |
|---|---|---|
| enqueued **2026-09-04** (one-time `--with-backfill` bulk) | 9,779 | **all `EXPIRED`** on first drain (≥ 6 days old ≫ every cutoff) |
| **S1 2026-09-08** live | 6 | `EXPIRED` (≥ 2 days old) |
| **S2 2026-09-09** live | 35 | `EXPIRED` |
| **S3 2026-09-10** live | 23 | `EXPIRED` |
| by band | HIGH 5,837 · MEDIUM 3,216 · LOW 767 · **CRITICAL 23** | — |

**CRITICAL rows (23), reviewed by age + substance:** all 23 were enqueued on **2026-09-04** (the
bulk backfill) — none is a live, recent event; every `enqueued_at_utc` is ≥ 6 days before any
possible activation. Event types: `INSIDER_TRANSACTION`, `QUARTERLY_FILING`, `REGULATION_FD`,
`MATERIAL_AGREEMENT`, `DEBT_FINANCING`, `ACQUISITION_DISPOSITION`, `AGREEMENT_TERMINATED`,
`RESTRUCTURING` (×1), `DELISTING_NOTICE` (×1). A CRITICAL label does **not** justify sending a
six-day-old alert — even the `DELISTING_NOTICE` and `RESTRUCTURING` rows are stale (their
actionable window as *news* has passed; the underlying facts, if still relevant, resurface on the
next filing). **All 23 → `EXPIRED`.** The full list (`delivery_id`, `event_id`, `symbol`,
`enqueued_at_utc`) is at `results/task117_output_closure_evidence/critical_backlog_review.csv`
(git-ignored) for a human to eyeball before any activation.

**Audit trail:** `expire_stale` writes an `EXPIRED` `intelligence_delivery_log` row per row and
sets `suppress_reason = "stale_card: <age>h > <cutoff>h <route> cutoff"`. **No row is deleted;
no old row is marked SENT.**

## Non-executed production activation steps (do NOT run here)

1. **Decide intent** (product): is `intelligence_delivery` meant to deliver, or stay a rendered
   audit trail? If stay dry-run: correct the dashboard / any "Intelligence delivery enabled"
   copy to say "rendered, not delivered" and stop here.
2. If deliver: on a **copy** of `ingestion_ledger.db`, run `DeliveryOutbox(copy).expire_stale()`
   once → confirm 9,843 → ~0 PENDING, ~9,843 EXPIRED, 0 SENT.
3. Add `config.deliver_intelligence_cards: bool = False` to `service/config.py` (env
   `TALONX_INTEL_DELIVER_CARDS`, default off).
4. Wire one call into `runner.run_poll_loop` after `poll_cycle`:
   `await process_pending(self.stores.delivery, TelegramSender(), enforce_age_cutoff=True,
   dry_run=not self.config.deliver_intelligence_cards, route=None, limit=20)`.
   With the flag off this is a no-op that only expires stale rows.
5. Deploy with the flag **off**. Verify a full session: outbox expires stale rows, sends
   nothing, `intelligence_delivery_log` shows `EXPIRED` only.
6. Only then, in a separate change, flip `TALONX_INTEL_DELIVER_CARDS=1` and verify with an
   intercepted transport before touching the real Telegram token.
7. Rate-limit: `limit=20` per cycle + the per-send retry inside `TelegramClient` caps burst.
