# Dashboard / actual-SPA acceptance

**No browser / screenshot tool is available in this session.** The SPA
(`dashboard_web.py` → `talonx_ops/dashboard_read.py` → `/api/section/<name>`) is
verified through its read-model API + the delivery outbox surface, against
isolated / preserved data. The **exact unverified render gate** is stated at the
end — API-only checks are NOT called rendered acceptance.

## End-to-end rehearsal (isolated) — `tests/test_task117_delivery_runner_integration.py`

One `IntelligenceService` on an isolated ledger, `TelegramSenderAdapter`
monkeypatched to an intercepting recorder:

| step | result |
|---|---|
| source event → enrichment → durable queue | `enqueue_card` → `intelligence_delivery` row `PENDING` |
| delivery **disabled** (default) | `deliver_cycle` mode `disabled` → row **held PENDING**, `held_reason="delivery_disabled"`, `HELD` log line, **nothing sent** |
| **restart** with delivery **enabled** | fresh `IntelligenceService` on the same ledger → `deliver_cycle` mode `enabled` → the **same** row → intercepted transport ack → `SENT` (fresh event not lost by the disabled cycle) |
| fresh event **alongside stale backlog** | `test_enabled_cycle_expires_stale_backlog_and_delivers_only_fresh` — stale → `EXPIRED`, fresh → `SENT`, `inter.sent == [fresh]` (backlog not flooded) |
| **transient failure** | `RETRY` (attempts++, `next_retry_at`) then success (pre-existing `test_retry_on_transient_then_succeeds`) |
| **ambiguous** outcome | `test_ambiguous_send_is_durable_and_not_retried` — row → `AMBIGUOUS`; a 2nd cycle does **not** re-attempt |
| **source failure while delivery work remains** | `deliver_cycle` is a separate step after `poll_cycle`; a poll error does not prevent the drain, and the `asyncio.wait_for` timeout means a slow drain does not block the next poll |
| correct event/session timestamps | `parse_acceptance_datetime(..., source="submissions")` = genuine UTC (`test_task117_acceptance_timezone.py`); `bucket_session` on genuine UTC |
| startup failure + repeated-start protection | `test_task117_startup_verdict.py` — `FAILED_WITH_RESIDUALS` verdict + `ConcurrentStartError` |
| EOD snapshot + ownership-safe shutdown | `prospective close` writes `lane_accounting_eod.json`; `stop_stack` ownership-safe reap (pre-existing `controlled_shutdown_complete` assert) |

## Rendered-SPA inspection targets (data verified; pixels not)

| SPA element | backing read-model | state after this change |
|---|---|---|
| Active-V2 near-miss funnel | `build_funnel(execution_allowlist="auto")` | scoped to the enforced 39 — `[ADC, INTC]`, not `[…, MUNEX, NMZ, PML]` (D1, unchanged from `task117_output_closure`) |
| Telegram receive owners | `count_telegram_get_updates_owners()` | shim+worker = **1** logical owner (D2, unchanged) |
| current-session EOD tile | `_v2_eod_state(now=self.now)` | prior-session reconciliation row surfaced as a note, not applied (D3, unchanged) |
| **ingestion vs processing vs queued vs sent** | `DeliveryOutbox.counts_by_state()` now returns `{PENDING, SENT, FAILED, EXPIRED, AMBIGUOUS, SUPPRESSED}` as **distinct** counts | a tile can render **queued (PENDING) ≠ sent (SENT)** ≠ **held** ≠ **expired** ≠ **ambiguous**. A healthy poll loop no longer implies messages are sent — `deliver_cycle`'s per-route result (`held` / `delivered` / `simulated` / `expired` / `ambiguous`) is on the cycle summary. |
| honest last-send time | `dispatch_audit.last_telegram_push` now includes the earnings-heads-up domain (D7 from the prior task) | unchanged |

## Exact unverified render gate

**Not verified:** the pixels. To close this, an operator with a browser runs
`python dashboard_web.py` against a copy of
`results/task117_day3_eod_20260910T202656Z/db/*.postclose` (copied to
`~/.talonx/`), opens `http://localhost:8787`, and confirms visually:

1. Active-V2 funnel near-miss list = `ADC, INTC` only.
2. Telegram receive = 1 owner, no "DEGRADED".
3. EOD tile = the current session's state (or `NOT_DUE_YET`), with any
   prior-session row shown as a labelled note.
4. A **delivery panel** showing `PENDING / SENT / FAILED / EXPIRED / AMBIGUOUS`
   as separate numbers, and (when delivery is disabled) a "delivery disabled —
   N cards held" banner rather than a green "sent" indicator.

Item 4's tile is **not yet built** — the read-model data is in place
(`counts_by_state`, `deliver_cycle` summary); wiring it into `dashboard_read`'s
`intelligence` / `paper_eod` section is a follow-up in `remaining_gaps.md`.
Screenshots, when produced, must be labelled **isolated fixture** — not
production.
