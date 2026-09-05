# Task 79G Stage 2 — Controlled Test-Path (PIV_LIFECYCLE_PROBE) Plan

**This document is a PROPOSAL requiring Task 80's explicit authorisation. Nothing here activates
anything — no `paper_entry_settings.json` was created, no probe was run against a real account,
and `talonx_piv/lifecycle_probe.py` was not modified.**

## What already exists (reused, not rebuilt)

`talonx_piv/lifecycle_probe.py` (Task 65B Part D, hardened by every later safety task through
Task 78I unchanged) — an operator-confirmed, single, isolated PAPER order lifecycle probe.

## Unique source/identity and classification

- `source="PIV_LIFECYCLE_PROBE"` on every event/order/position it touches (a member of
  `lifecycle.ALLOWED_ORDER_SOURCES`, structurally distinct from `"STRATEGY"`).
- `alpha_evidence=False` on every event.
- `notification_class="PIV_TEST"` (via `events.notification_class_for`, derived automatically
  from `source`).
- Symbol: `AAPL` (Alpaca-liquid, predeclared in code — `lifecycle_probe.PROBE_SYMBOL`, not chosen
  from today's price action).
- **No arbitrary event can self-authorise as a probe** — `source` is set exclusively by this
  module's own two call sites (`run_piv_lifecycle_probe`/`close_piv_lifecycle_probe`), never
  derived from caller-supplied input.

## Exact injection boundary

`SessionRunner._run_probe` → `lifecycle_probe.run_piv_lifecycle_probe(config, events, lifecycle,
explicit_confirmation=self.probe_enabled, now_et_time=...)`, itself only reachable when
`self.probe_enabled` is `True` — set exclusively from `cli.py`'s `--confirm-piv-lifecycle-probe`
flag on `start`/`supervise`. `run_piv_lifecycle_probe` additionally requires (fresh-checked, not
cached):
1. `not config.real_capital and config.paper_trading` and `config.broker_endpoint ==
   PAPER_ENDPOINT` (else `PROBE_BLOCKED_REAL_CAPITAL_OR_NON_PAPER_STATE` /
   `PROBE_BLOCKED_NON_PAPER_ENDPOINT`).
2. `now_et_time >= PROBE_CUTOFF_ET` (15:00 ET — predeclared, not tunable per-run) — the probe only
   fires if the natural strategy path has had the whole day first.
3. No `STRATEGY`-sourced `PAPER_ORDER_SUBMITTED` already observed today
   (`natural_strategy_lifecycle_observed`) — skipped entirely if natural trading already occurred.
4. `lifecycle.reconcile()["matched"]` — refuses on any unreconciled broker/internal mismatch.
5. No existing open position in `AAPL`.

**Newly confirmed this task (empirically, not merely by code reading)**: the probe's entry call
ALSO passes through `order_intent`'s own `PAPER_ENTRY_DISABLED_FOR_TICKER` guard — identical to a
natural entry. A live test against a fresh `PaperLifecycle` with `AAPL` NOT present in
`paper_entry_settings.json` (today's default — the file does not exist) produced
`PROBE_ENTRY_FAILED: PAPER_ENTRY_DISABLED_FOR_TICKER`, confirming the CLI flag alone does **not**
activate the probe — Task 80 must ALSO create `paper_entry_settings.json` with `{"AAPL": true}`
for the probe to be able to submit anything. This is a genuine, previously-implicit safety
property, now explicitly verified and documented (not a defect — two independent operator actions
are required, which is the more conservative posture).

With `AAPL` enabled, a fresh empirical run (fake broker, isolated state) completed the full
lifecycle: entry submitted → position opened → controlled exit submitted → position closed, with
zero residual state.

## Components exercised vs. bypassed (coverage matrix)

| Component | Exercised by the probe? | Evidence |
|---|---|---|
| `order_intent`'s full hardened boundary (action-intent, quantity, source allowlist, pyramiding/pending-entry/PAPER-disabled/unexpected-short guards, oversell/duplicate-sell guard) | **YES** | fresh empirical run above; `test_task65b_lifecycle_probe.py` |
| `AlpacaPaperClient.submit_order`/`get_order` (fill polling via `poll_order_until_terminal`) | **YES** | same |
| Execution ownership (`broker.py`'s gate) | **YES** — same chokepoint as every other order | code read; not separately re-run live (would require acquiring the real lock) |
| `PaperLifecycle.reconcile()` (pre-check + post-close) | **YES** | same |
| EOD flatten (a still-open probe position is flattened exactly like a natural one) | **YES** (structural — `eod_lifecycle.py` operates on `lifecycle.state.positions` without discriminating by `source`) | code read |
| `piv_events.jsonl` / existing `EventBus` Telegram fan-out | **YES** — the SAME pre-existing (Task 64/69Q) best-effort Telegram send every `PivEvent` gets, regardless of source | code read (`events.py::EventBus.emit`) |
| `decision_contract.decide()` | **NO** — the probe never constructs a `Decision` at all | code read (`lifecycle_probe.py` has no import of `decision_contract`) |
| `decision_ledger` (durable `DecisionRecord`) | **NO** | same |
| `notification_outbox` (Task 77I alert classification/dedup/retry) | **NO** | same |
| `shadow_ledger` (causal shadow tracking) | **NO** | same |
| `gemini_enrichment` | **NO** | same |

**Only the broker/lifecycle layer is covered by the existing probe.** The four newer,
decision-centric ledgers (decision, notification, shadow, Gemini) are exercised elsewhere — by
`test_task77i_end_to_end.py`/`test_task78i_stage5_rehearsal.py`'s synthetic `APPROVED`-strategy
fixtures — never by a live probe run, and this task does not close that gap (see `remaining_issues.md`).
A single successful probe run therefore proves the broker-mutation chokepoint end-to-end; it does
NOT prove the decision/alert/shadow/enrichment layers against a live account.

## Proposed limits (require Task 80's explicit approval — none of this is active)

- Symbol: `AAPL` (fixed, not configurable per-run).
- Max entry quantity/notional: `PROBE_QUANTITY = 1.0` share (fixed in code; at ~$100-250/share for
  AAPL, notional exposure is small and singular — Task 80 should independently confirm current
  AAPL price before approving).
- Max new entries: **1** (structural — `run_piv_lifecycle_probe` refuses if `AAPL` is already
  open, and `_probe_attempted` is a one-shot per-session flag in `SessionRunner`).
- Session/time window: only after `PROBE_CUTOFF_ET` (15:00 ET = 20:00 BST on 2026-08-28) AND only
  if no natural strategy order occurred first.
- Expiry/exit: closed by `SessionRunner`'s own `_close_probe` (called every subsequent tick while
  `_probe_position_open`) or, if still open, by the guaranteed EOD flatten at 15:50 ET.
- PAPER-account verification: enforced (`config.real_capital`/`paper_trading`/`broker_endpoint`
  checked fresh on every call, not cached).
- Long-only: structural — `order_intent`'s `ActionIntent` enum has no short-opening value.
- Freshness/quantity checks: the probe does not consult symbol-level data freshness at all (it is
  not a market-data-driven signal) — its own guard set (reconciliation, existing-position,
  PAPER-entry-enabled) is the complete gate.
- Execution ownership: enforced identically to any other order.

## Failure-mode handling (reused, not reimplemented)

- Timeout/unconfirmed submission: `UNCONFIRMED_TIMEOUT` sentinel + `reconcile()`-driven resolution
  (Task 77I Stage 1) — identical mechanism, no probe-specific code.
- Partial fill: the Task 77I/78I `apply_broker_update` fix (incremental fill tracking,
  `remaining_quantity`) applies identically.
- Duplicate events: `order_intent`'s `stable_id`-based duplicate-intent-id guard applies
  identically; `natural_strategy_lifecycle_observed` additionally prevents a redundant probe
  attempt if natural trading already happened.
- Crash/restart: the probe holds no in-memory-only state beyond `SessionRunner._probe_attempted`/
  `_probe_position_open` (in-memory flags) — a crash mid-probe leaves the SAME
  `lifecycle_state.json`/`UNCONFIRMED_TIMEOUT` recovery path as any other order; a restarted
  session would not automatically resume/retry the probe (one-shot per invocation), but the
  position itself (if filled) remains tracked and would still be flattened by EOD.
- Uncertain broker state: resolved via the same `reconcile()` path as any other order — no
  probe-specific remediation exists, and none should be invented (matches the general "no
  automatic remediation for unknown exposure" requirement).

## Separate record-keeping

- Test notifications: N/A — no `notification_outbox` record is created by the probe today (see
  coverage matrix). The probe's own events DO reach Telegram via the pre-existing `EventBus`
  fan-out, tagged `notification_class=PIV_TEST` — visually/statistically distinguishable from
  `NATURAL_SIGNAL`/`PAPER_EXECUTION` classes at the raw-event level, even without a
  `NotificationOutbox` record.
- Test shadow outcomes: **UNAVAILABLE** — `shadow_ledger` is never invoked for probe traffic (see
  coverage matrix). This is not "prepared but disabled"; it is genuinely not wired, and this task
  does not wire it (would be a material scope expansion the night before a handoff).
- PAPER probe activity vs. natural strategy activity: already separated at the ledger level —
  `reporting.build_session_report`'s `natural_strategy`/`piv_test_traffic` sections (Task 69Q Part
  4, unchanged) split by `source`.

## Cleanup/reconciliation procedure

No blind repeated submission exists anywhere in this path — `_probe_attempted` is a one-shot flag,
`natural_strategy_lifecycle_observed` prevents redundant firing, and `order_intent`'s own
duplicate-intent-id/pending-entry guards would reject a genuine accidental re-invocation. Standard
recovery is the SAME as any other order: `PaperLifecycle.reconcile()` (read-only) then, if
necessary, the existing `cli.py cleanup --confirm-paper-cleanup` command (bulk cancel/close,
requires explicit confirmation, out of scope for THIS task to run).

## Categories (for the launch pack)

1. **Natural candidates** — generated by live market conditions through
   `talonx_piv.decision_engine.DecisionEngine`; remain subject to `StrategyApprovalStatus`
   (`UNVALIDATED` today — no real natural candidate can reach the broker, by design).
2. **Controlled probe** — this document's proposal; `source=PIV_LIFECYCLE_PROBE`,
   `alpha_evidence=False`, excluded from all strategy/alpha statistics; requires Task 80's
   explicit `--confirm-piv-lifecycle-probe` AND a populated `paper_entry_settings.json`.
3. **Research-only shadow experiment** — a future, NOT-implemented, NOT-authorised mode; nothing
   in the current codebase provides shadow-tracking for anything other than an `APPROVED`
   (test-fixture-only) strategy decision. Not proposed for activation here.
