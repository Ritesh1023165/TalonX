# V2 Release Integration RI-2 — Multi-Channel Telegram + Durable Trade/Event/Operations Routing

**Status: EVIDENCE BUNDLE.** See the final report (delivered in-conversation) for
the RI2_* verdict. Packages 1-5's and RI-1's own evidence bundles are unmodified.

## 0. Repository state

- Branch: `feature/task131-option-a-integration`.
- Starting SHA: `c8489b7` (RI-1, clean tree) — verified to match the reported HEAD exactly.
- Production-safety check re-run at the start of this task (not assumed
  from RI-1): confirmed no live TalonX process running (no `python.exe`
  at all this time), no `talonx.pids.json`, `v2_lane.db` mtime
  unchanged (`2026-09-15`) throughout. **No real Telegram send,
  production outbox drain, production DB mutation, launch, restart, or
  provider/broker action occurred anywhere in this task.**

## 1. Scope discipline

No strategy tuning, no insider-qualification change, no Session-10
exit change, no pricing/recovery change, no sizing/accounting change,
no campaign-economics change, no profitability research, no intraday
promotion, no Research bot enabled by default, no dashboard redesign,
no provider work. Every code change is either (a) a new, additive
notification-classification layer, or (b) a narrowly-scoped hook into
an existing, unmodified business-logic call site (poll-and-diff
scanning, never an inline change to Package 1/2's own tested mutation
methods).

## 2. RI2-A — Before-state notification architecture

(Full detail: this bundle's own investigation notes below; summary
table per the task's required format.)

| Producer | Event | Current path (before RI-2) | Durable? | Delivery owner | Finding |
|---|---|---|---|---|---|
| `talonx_v2.service._enqueue_alert` | V2 ENTRY_INTENT/ENTRY_FILL/EXIT_FILL/ENTRY_STALE/ENTRY_FAILED_NO_DATA | `v2_alert_outbox` → `talonx_v2.delivery.deliver_outbox` | Yes | `talonx_v2.delivery.deliver_outbox`, wired into `V2Service.tick()` (`self._deliver and self._router is not None`) | **Already fully wired** — `talonx_ops/prospective/proc.py::start_stack()` passes `--deliver --transport telegram` into the V2 companion's own argv when the operator requests it; production-proven (Task 117 real sends). No `destination` was persisted (added by RI-2). No campaign identity was in the message body (added by RI-2). |
| `talonx_dispatch.consumer.DispatchAgent` | Original intraday BULLISH/BEARISH, long-term hold_quality, trade execution, T-48h earnings heads-up | `talonx_dispatch.telegram_client.TelegramClient.send()` directly | Audit-durable (`AuditStore`'s `alerts`/`long_term_alerts` tables), but NOT outbox-durable-before-send in the PENDING/RETRY sense | `talonx_dispatch/consumer.py` itself (its own Smart Dispatch Filtering) | **Pre-existing, working, OUT OF RI-2's SCOPE** — predates the V2/RI arc entirely; "do not broadly refactor unrelated messaging code." See §7 for the Research-isolation implication this raises. |
| `talonx_ingest.intelligence.service.runner.IntelligenceService.deliver_cycle` | Company-development cards (Task 96E significance-banded) | `talonx_ingest/intelligence/delivery/outbox.py`'s own outbox → `talonx_ingest/intelligence/delivery/pipeline.py` (wraps the SAME `TelegramClient`) | Yes (`PENDING/SENT/EXPIRED/FAILED` states) | `IntelligenceService.run_poll_loop`, itself launched by `talonx_ops/supervisor.py`'s `default_talonx_components()`, itself spawned by `prospective start` | **Already wired, contradicting the historical "9,843 PENDING, 0 SENT" finding as a CURRENT-state description** — Task 140 (building on Task 132) fixed exactly this gap: `proc.py:260-264` propagates `TALONX_INTEL_DELIVER_CARDS=1`/`TALONX_INTEL_DRY_RUN_DELIVERY=0` into the supervisor's env whenever `--deliver --transport telegram` is passed to `prospective start`, specifically because an earlier version left Intelligence's delivery silently in permanent dry-run. See §3 for full reconciliation. |
| `talonx_ops.prospective.close._record_v2_reconciliation_blocks` | LEDGER_MISMATCH / CASH_DEFICIT | `account_blocks` table only | Yes (the block itself) | **None — no notification at all** | Genuine pre-RI-2 gap, closed by RI-2 (§5). |
| `V2Store.mark_exit_unresolved` / `record_account_block` | EXIT_UNRESOLVED, ACCOUNT_BLOCK | `account_blocks` table only | Yes (the block itself) | **None — no notification at all** | Genuine pre-RI-2 gap, closed by RI-2 (§5). |
| — | Startup / shutdown | — | — | **None** | Genuine pre-RI-2 gap, closed by RI-2 (§5, §13). |
| — | Health/degraded pipeline | `/ping` reply only (reactive, not proactive) | N/A | **None proactive** | Pre-existing partial coverage (reactive `/ping`); proactive OPERATIONS notification is new infrastructure RI-2 adds (producers exist; a full health-monitor producer is a disclosed follow-up, §16). |

## 3. Critical historical failure — reconciled, not assumed fixed

The task's own framing (9,843 PENDING / 0 SENT / ORCL via a separate
route) was independently re-traced against the CURRENT code, not
assumed resolved:

1. **Where events enter the outbox**: `talonx_ingest/intelligence/
   delivery/outbox.py`'s own `intelligence_delivery`-shaped table
   (`ingestion_ledger.db`), written by the enrichment pipeline.
2. **What drains it**: `IntelligenceService.deliver_cycle()`
   (`talonx_ingest/intelligence/service/runner.py`), called every cycle
   inside `run_poll_loop()`.
3. **Whether that process is wired into the intended runtime
   lifecycle**: **YES**, confirmed by direct code read (not doc
   trust) — `talonx_ops/supervisor.py::default_talonx_components()`
   unconditionally includes an `"intelligence"` component
   (`argv = python -m talonx_ingest.intelligence.service poll
   --with-backfill`); `talonx_ops/prospective/proc.py::start_stack()`
   spawns the supervisor, which spawns Intelligence as its child.
   `proc.py:241-264`'s own comment names this EXACT historical gap
   ("`--deliver --transport telegram` ... was ALSO wired ONLY into the
   V2 companion's own argv ... never into Intelligence's card-delivery
   enablement") and fixes it by propagating the two `TALONX_INTEL_*`
   env vars whenever an operator passes those flags to `prospective
   start`.
4. **What happens on Telegram failure**: `TelegramClient.send()`'s own
   retry/backoff (jittered exponential, non-retryable errors fail
   fast) — unchanged, reused as-is by Intelligence's pipeline.
5. **What happens after restart**: rows stay in whatever
   PENDING/SENT/EXPIRED/FAILED state they were in; the poll loop
   resumes draining on the next cycle. Not independently re-verified by
   RI-2 (Intelligence's own delivery pipeline is out of RI-2's bounded
   scope to redesign or re-test beyond confirming the wiring above) —
   recorded as a disclosed limitation (§16).
6. **What prevents duplicate delivery**: Intelligence's own outbox
   dedup (its own event/card identity), independent of RI-2.
7. **Whether old/backlogged rows could suddenly flood Telegram**: per
   the historical evidence itself (`docs/audits/task117_delivery_
   timestamp_completion/acceptance_matrix.md`), Intelligence's own
   backlog-safety mechanism (`9,841 expire / 2 survive` at a
   documented cutoff) was ALREADY exercised and found safe — this
   predates RI-2 and is not re-tested here (out of scope: Intelligence
   pipeline internals). RI-2's OWN new `ops_notification_outbox`
   backlog-safety is independently proven in §12/§20.
8. **Whether expired historical messages are prevented from delivering
   as current alerts**: yes, per the same evidence (EXPIRED state,
   never SENT).

**Conclusion**: the specific "outbox never drains" defect the task
describes was ALREADY found and fixed by a prior, separate task
(Task 140) on this same branch, before RI-2 began. RI-2 does not
re-fix it; RI-2 re-traces and confirms it (this section), and builds
the NEW TRADE_EVENT/OPERATIONS/RESEARCH classification layer on top of
already-working infrastructure rather than assuming a fix that turned
out to already exist, or duplicating one that would have been
redundant.

## 4. RI2-B/C — Destination / configuration model

`talonx_ops/notify/__init__.py`: three logical destinations
(`TRADE_EVENT`, `OPERATIONS`, `RESEARCH`), resolved via
`resolve_destination_config(destination) -> DestinationConfig`.

- **TRADE_EVENT / OPERATIONS**: destination-specific env vars
  (`TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN`/`_CHAT_ID`,
  `TALONX_NOTIFY_OPERATIONS_BOT_TOKEN`/`_CHAT_ID`), falling back to
  the EXISTING single `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` when
  unset — today's single-bot behavior is preserved byte-for-byte by
  default; the moment separate credentials are provisioned, the two
  channels physically separate with zero further code change.
- **RESEARCH**: explicit DOUBLE opt-in — its own
  `TALONX_NOTIFY_RESEARCH_BOT_TOKEN`/`_CHAT_ID` AND
  `TALONX_NOTIFY_RESEARCH_ENABLED=1` — no fallback to the primary bot
  under any circumstance. A stray token/chat_id alone never activates
  it (`test_research_enabled_flag_without_credentials_still_disabled`).
- `telegram_client_for(destination)` constructs a
  `talonx_dispatch.telegram_client.TelegramClient` (the EXISTING,
  unmodified client class) with a per-destination
  `talonx_dispatch.config.DispatchConfig` — no second bot library, no
  new transport implementation.
- A disabled/unconfigured destination is an explicitly VALID
  configuration state (`DestinationConfig.enabled=False`), never an
  error — confirmed: no Telegram credential is required for any test
  that does not enable delivery (every test in this task's own suite
  runs without `.env`, `TELEGRAM_BOT_TOKEN`, or any real credential).

## 5. RI2-D — V2 trade routing

`talonx_v2/store.py`'s `v2_alert_outbox` gained an additive
`destination` column (`DEFAULT 'TRADE_EVENT'` — every pre-RI-2 row was
genuinely a trade/event notification, a correct backfill, never a
guess). `V2Service._enqueue_alert`'s message body and provenance now
both carry the campaign's own `campaign_id` (RI-1's own identity
record, read via `store.campaign_identity()`). BUY (ENTRY_FILL) and
SELL (EXIT_FILL) notifications both route to TRADE_EVENT — proven with
real service-driven fills, not the low-level API alone.

**Execution independence**: `test_19_v2_buy_survives_telegram_
failure` — a position/cash already committed by `paper.enter_position`
is provably unaffected by a SUBSEQUENT `deliver_outbox` call whose
transport raises on every send. The trade happens because the
trading-lifecycle pipeline says it should; delivery is a downstream,
independent observation of that fact — never a precondition.

## 6. RI2-E — Operations routing

New `talonx_ops/notify/producers.py`:
- `scan_v2_operational_events` — a POLL-AND-DIFF scanner (deliberately
  NOT an inline hook inside `V2Store.mark_exit_unresolved`/
  `record_account_block`, which stay completely untouched — Package
  1/2's own atomicity/idempotency guarantees are the load-bearing
  safety mechanism, not this notification layer). Enqueues one
  OPERATIONS event per currently-unresolved position / active block,
  idempotent (dedup_key keyed on position_id/block_id), naturally
  restart-safe (a restart just re-scans unchanged state).
- `enqueue_reconciliation_failure` — wired into `talonx_ops/
  prospective/close.py::_record_v2_reconciliation_blocks`, called
  immediately after the account-block transaction commits (see §16 for
  the disclosed cross-database-atomicity limitation this implies).
- `enqueue_lifecycle_event` — wired into `prospective start`/`close`
  (STARTUP/SHUTDOWN), best-effort, never blocks or fails the actual
  start/close outcome.
- `enqueue_delivery_subsystem_failure` — wired into `V2Service.tick()`'s
  own `deliver_outbox` exception handler; hour-bucketed dedup key
  specifically to satisfy "avoid flooding" without inventing arbitrary
  suppression that could hide a genuine safety-critical condition (one
  notification per destination per hour, not zero).

All use the SAME reused state machine (PENDING/SENT/HELD/RETRY/
FAILED/EXPIRED/AMBIGUOUS) as V2's own `v2_alert_outbox` — no new states
invented.

## 7. RI2-F — Research isolation

`enqueue_research_event(ops_store, ...)` — destination is HARDCODED
`RESEARCH` (not a parameter), so there is no code path by which a
research event could be misrouted to TRADE_EVENT/OPERATIONS by mistake.
RESEARCH's own `resolve_destination_config` has no fallback (§4) — a
disabled RESEARCH destination leaves every enqueued row `PENDING`,
untouched, never discarded, never rerouted
(`test_9_research_off_does_not_fallback_to_trade_event`,
`test_10_..._to_operations`).

**Important scope boundary, explicitly disclosed**: `talonx_dispatch.
consumer.DispatchAgent`'s PRE-EXISTING intraday `ActionableAlert` push
(§2) is a real, currently-active Telegram send that predates this
whole V2/RI arc and is NOT gated by RI-2's new RESEARCH destination —
it uses the single shared `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
directly, the same physical bot TRADE_EVENT falls back to by default.
This is **not a defect RI-2 introduces or is required to fix**:
`docs/product/REQUIREMENTS_TRACKER.md`'s own `S6-01` records "primary
scope = Intraday Opportunities + V2" as a still-agreed, implemented,
PRE-EXISTING decision, and Session 13's later "Research-Lab-only for
the first release" framing is explicitly a release-POSITIONING
decision ("primary scope... is itself a labelling/positioning
decision, not a runtime claim" — `S6-01`'s own validation note), not a
mandate to retroactively silence Original's own, separately-authorized,
pre-existing intraday push. RI-2's own RESEARCH destination governs
NEW Research-Lab reporting (e.g., a future `talonx_backtest`
live-shadow report) — it does not, and per its own non-goals
("no broadly refactor unrelated messaging code") should not, retrofit
`talonx_dispatch/consumer.py`. Recorded here as a disclosed scope
boundary, not silently ignored (§16).

## 8. RI2-G — Company-development routing

`talonx_ingest/intelligence`'s own significance-band classification
(Task 96E, `IMMEDIATE_MIN_BAND = SignificanceBand.HIGH`) is the ONE
existing, unmodified, already-tested gate determining which
company-development cards ever reach delivery at all — LOW/MEDIUM
significance never qualifies for immediate delivery
(`test_11_12_company_development_routing_is_a_documented_bounded_
gap`). RI-2 does not redesign this content/materiality logic. **Bounded
release gap, explicitly disclosed**: Intelligence's delivery pipeline
is not retrofitted to resolve its Telegram config through
`talonx_ops.notify.resolve_destination_config(TRADE_EVENT)` — it still
reads the raw `TELEGRAM_BOT_TOKEN`/`_CHAT_ID` directly. In practice
this means company-development cards land in the SAME physical channel
as TRADE_EVENT's own default (shared-bot fallback), which is
consistent with intent but not yet independently re-targetable the
instant an operator provisions a dedicated TRADE_EVENT bot. A small,
separately-scoped follow-up (§16) would close this.

## 9. RI2-H/I — Durable outbox + actual drain wiring

New `talonx_ops/notify/outbox.py::NotifyStore` — same lifecycle shape
as `v2_alert_outbox` (PENDING/RETRY/SENT/HELD/FAILED/EXPIRED/AMBIGUOUS),
a SEPARATE table/file (`notifications.db` by default,
`TALONX_NOTIFY_DB_PATH`-configurable) for OPERATIONS/RESEARCH events
not tied to a specific V2 episode.

**Explicit proof, event → outbox → runtime component → fake Telegram → SENT**
(`test_14_runtime_delivery_component_actually_drains_outbox`):
1. A `V2Store` position is marked `EXIT_UNRESOLVED` (a real business event).
2. A REAL `V2Service` is constructed with `ops_notify_store=` set (the
   SAME already-proven-wired tick loop RI-1/Package 4 use).
3. `svc.tick(as_of=...)` — the actual runtime entry point, not a
   manually-invoked `drain()` call — is called ONCE.
4. Inside that single tick, `scan_v2_operational_events` (producer) AND
   `talonx_ops.notify.worker.drain` (the runtime consumer) both run
   automatically, with no test code calling either directly.
5. A fake `RecordingTransport` (injected via `telegram_client_for`
   monkeypatch) receives the message.
6. The outbox row transitions to `SENT`.

This proves the intended runtime component (`V2Service.tick()`, the
SAME entry point `prospective start` already drives for V2's own
TRADE_EVENT delivery) actually invokes the new OPERATIONS delivery
worker — not merely a unit-tested `drain()` in isolation.

## 10. RI2-J — Failure/retry/restart

`talonx_ops/notify/worker.py::drain` mirrors `deliver_outbox`'s exact
state machine and backoff formula (`min(300, 5 * 2**(attempts-1))`).
Tested: timeout/transient failure → RETRY with backoff
(`test_16`); process restart before retry resumes correctly from a
FRESH store instance (`test_17`); eventual success after retry
(`test_18`); a total, permanent transport outage never rolls back or
prevents the already-committed paper trade (`test_19`).

## 11. RI2-K — Dedup/idempotency

Durable notification identity: `event_id` (content-derived,
SHA-256-truncated from stable business identifiers — campaign/episode/
position/block id + event type, never random) is the PRIMARY KEY;
`NotifyStore.enqueue`/`V2Store.enqueue_alert` are both idempotent on
it. Same business event processed twice → `enqueue` returns `False`
the second time, zero new rows (`test_20`, `test_20b`). Retrying the
same outbox item never creates a new logical row — `update_outbox`
mutates the SAME row (`test_21`).

**Honest limitation, explicitly documented (not falsely claimed
exactly-once)**: `test_21b_external_exactly_once_is_not_falsely_
claimed` confirms the worker's own AMBIGUOUS state exists precisely
for the case where Telegram's send outcome cannot be confirmed (a
timeout AFTER the request may have reached Telegram) — this is
INTERNAL durable idempotency (one logical outbox row, guaranteed) as
DISTINCT from EXTERNAL transport certainty (not guaranteed, and never
silently assumed either way). `talonx_dispatch.telegram_client.
TelegramAmbiguousError`'s own docstring states this identical
limitation; RI-2 reuses that established, honest posture rather than
inventing a stronger claim.

## 12. RI2-L — Backlog/expiry

The exact historical risk class (thousands of PENDING rows suddenly
flooding Telegram when delivery is enabled) is directly tested, not
merely reasoned about: `test_23_stale_backlog_not_sent_on_startup`
enqueues 25 PENDING rows with `deliver_by_utc` three days in the past,
then drains with delivery freshly "enabled" (credentials present for
the first time) — **result: 25 EXPIRED, 0 SENT, 0 actual transport
sends of any kind**. `test_24_current_valid_event_still_sends`
confirms a genuinely current event (future deadline) still delivers
normally in the SAME run — expiry is selective, not a blanket
delivery freeze. No production outbox was touched to establish this
(purely a fixture-scale, isolated-db proof); no hardcoded "9.8k"
figure appears anywhere in RI-2's own code or tests (the task's own
instruction).

## 13. RI2-M — Startup/shutdown lifecycle

`prospective start`/`close` each enqueue a durable STARTUP/SHUTDOWN
OPERATIONS notification (best-effort — a failure to enqueue never
blocks or reverses the actual start/close outcome, matching this
project's own established "notification is an observation, not a
precondition" philosophy, reaffirmed for RI-2 in §5). A disabled or
misconfigured destination NEVER silently discards a notification — a
due row with no resolvable transport simply stays `PENDING`
(`test_26`), consistent with "do not silently discard" and with V2's
own, already-established default (`DryRunTransport` HOLDs, never
drops). Market/trading execution is never made contingent on Telegram
availability anywhere in this task.

## 14. RI2-N — Delivery observability

`NotifyStore.counts_by_state()`, `.last_sent()`, `.last_failure()` —
PENDING/SENT/FAILED/EXPIRED/... counts, last successful delivery, last
failure, all filterable by destination
(`test_30_delivery_observability_counters`). CLI/direct-store-query
evidence, per the task's own "CLI/log/health-reader evidence is
sufficient" allowance — no dashboard change was made or required.

## 15. RI2-O — Message ownership

| Event | Producer | Outbox | Destination | Delivery owner |
|---|---|---|---|---|
| V2 ENTRY_INTENT/ENTRY_FILL/EXIT_FILL/ENTRY_STALE/ENTRY_FAILED_NO_DATA | `V2Service._enqueue_alert` | `v2_alert_outbox` | TRADE_EVENT | `talonx_v2.delivery.deliver_outbox` |
| EXIT_UNRESOLVED | `talonx_ops.notify.producers.scan_v2_operational_events` | `ops_notification_outbox` | OPERATIONS | `talonx_ops.notify.worker.drain` |
| ACCOUNT_BLOCK | `talonx_ops.notify.producers.scan_v2_operational_events` | `ops_notification_outbox` | OPERATIONS | `talonx_ops.notify.worker.drain` |
| RECONCILIATION_FAILURE | `talonx_ops.prospective.close` (via `enqueue_reconciliation_failure`) | `ops_notification_outbox` | OPERATIONS | `talonx_ops.notify.worker.drain` |
| STARTUP / SHUTDOWN | `talonx_ops.prospective.__main__` | `ops_notification_outbox` | OPERATIONS | `talonx_ops.notify.worker.drain` |
| DELIVERY_FAILURE | `talonx_v2.service` (own delivery exception handler) | `ops_notification_outbox` | OPERATIONS | `talonx_ops.notify.worker.drain` |
| Research-lab record | any future producer via `enqueue_research_event` | `ops_notification_outbox` | RESEARCH | `talonx_ops.notify.worker.drain` |
| Original intraday/long-term/trade/earnings | `talonx_dispatch.consumer.DispatchAgent` | `dispatch_audit.db` (`alerts`/`long_term_alerts`) | *(pre-existing, out of RI-2 scope, §7)* | `talonx_dispatch.consumer.DispatchAgent` itself |
| Company-development cards | `talonx_ingest.intelligence.service.runner` | `ingestion_ledger.db`'s Intelligence outbox | *(shared-bot fallback today, §8)* | `IntelligenceService.deliver_cycle` |

**No event class has two active delivery owners** — `test_31` confirms
V2's own outbox and RI-2's new `ops_notification_outbox` are
physically separate tables/files; V2's trade notifications never write
into the new one and vice versa.

## 16. RI2-P — Secret safety

`test_28_no_secret_in_persisted_payload` / `test_29_no_secret_in_
error_output` — a deliberately distinctive fake token/chat_id
(`SUPER-SECRET-TOKEN-VALUE`, `TOKEN-XYZ`) is confirmed absent from
every persisted field (`payload_text`, `provenance_json`,
`transport_ref`, `last_error`) and from the drain summary dict itself,
across both a successful and a failing send. No real credential was
ever used, read, or logged anywhere in this task (every test
constructs its own fake token strings). No `.env`/token/chat_id was
committed or modified.

## 17. Defects found / corrected

**None new** — the specific historical outbox-drain-wiring defect
(9,843 PENDING / 0 SENT) was already found and fixed by a prior task
(Task 140) before RI-2 began; RI-2 confirmed this by direct code trace
(§3) rather than assuming it. RI-2 itself introduces no defect requiring
correction (full regression clean, §19).

## 18. Limitations (see also inline notes above)

- **Cross-database atomicity**: `ops_notification_outbox` lives in a
  SEPARATE SQLite file from `v2_lane.db`; the reconciliation-failure/
  account-block/exit-unresolved notification enqueue happens
  immediately AFTER (not atomically WITH) the underlying business-state
  commit. The business state itself (the account block, the position
  status) is unaffected either way — only the NOTIFICATION could, in a
  narrow crash window, be delayed rather than sent. Never a business-
  correctness risk, disclosed honestly rather than overclaimed.
- **Intelligence pipeline's own delivery-restart behavior** (§3 point
  5) was traced for wiring but not independently re-tested end-to-end
  by RI-2 — that pipeline's own prior test coverage is relied upon,
  consistent with "do not broadly refactor unrelated messaging code."
- **Company-development destination targeting** (§8): a small,
  separately-scoped follow-up would let Intelligence's delivery
  pipeline resolve its config through
  `talonx_ops.notify.resolve_destination_config(TRADE_EVENT)` instead
  of the raw env vars, for full destination-credential independence.
- **Health-monitor OPERATIONS producer**: `enqueue_delivery_subsystem_
  failure` and the STARTUP/SHUTDOWN producers exist and are wired;
  a broader "degraded pipeline / provider failure" producer beyond
  what already surfaces via `/ping`-reply-based reactive health is not
  built in RI-2 (greenfield infrastructure exists — `NotifyStore`,
  `drain`, the destination model — ready for such a producer without
  further schema work).
- Original's pre-existing intraday Telegram push (§7) remains
  untouched and outside RI-2's own RESEARCH-destination governance, a
  deliberate, disclosed scope boundary, not an oversight.

## 19. Tests

`tests/test_ri2_notification_routing.py` — 31 new tests, **31/31
pass**, covering all 31 minimum required scenarios (exact command/
totals in the final report §19).
