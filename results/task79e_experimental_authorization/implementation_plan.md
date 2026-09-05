# Task 79E — Implementation Plan (as executed)

## Objective

Give an otherwise-eligible, natural, long-only bullish signal a narrowly-scoped
path to generate an **experimental** alert, research shadow position, and
optional bounded PAPER entry, while the underlying strategy remains
`UNVALIDATED` — without ever setting `strategy_approval_status = APPROVED`
to reach it, and without weakening the existing production approval gate for
any non-experimental decision.

## Design summary

1. **New, structurally distinct outcomes** (`decision_contract.py`)
   `Recommendation.EXPERIMENTAL_BUY` and `ExecutionStatus.
   ENTRY_ELIGIBLE_EXPERIMENTAL_PAPER` / `ENTRY_BLOCKED_EXPERIMENTAL_PAPER_NOT_PERMITTED`
   are new enum members, not flags on `BUY`. `Decision.experimental` /
   `Decision.experimental_id` are new fields kept strictly separate from
   `strategy_approval_status` — origin/permission/validation are three
   different concepts and none is ever used to fake another.
   `decide()` gained four new, all-defaulted-False/None keyword arguments;
   every pre-existing call site is byte-identical in behaviour
   (`test_task76s_decision_contract.py` 17/17 unchanged).

2. **A new, disabled-by-default permission object**
   (`talonx_piv/experimental_authorization.py`) — `ExperimentalAuthorization`,
   loaded only via `load_experimental_authorization(path)`, which returns
   `None` (no permission at all) for a missing file, a malformed file, or an
   explicit `"enabled": false` — fail-closed on every ambiguous case, exactly
   matching `execution_settings.load_paper_entry_settings`'s own posture.
   Strict parsing throughout (booleans never coerced from strings, `bool`
   excluded from the numeric-limit check even though it is an `int`
   subclass, every required binding field checked). Two independent
   re-validation entry points — `permits_entry` and `permits_paper_execution`
   — both return `(bool, reason)`, never a bare bool, and both are
   re-evaluated **fresh against the real wall clock** on every call; nothing
   is cached from an earlier check.

3. **Re-validated again at the true broker boundary** (`lifecycle.py`) —
   `_enforce_experimental_paper_guards`, called from inside `order_intent`'s
   `BUY_TO_OPEN` branch only when `source == "EXPERIMENTAL"`. Never trusts
   the decision layer's own prior check; re-derives permission from the
   caller-supplied identity fields and rejects (`PaperGuardError`) on any
   mismatch (id, account, symbol, date, strategy id/version, runtime_sha,
   expiry, per-entry quantity, missing reference price, notional budget
   exhausted, entry-count exhausted). A durable, restart-surviving budget
   ledger (`LifecycleState.experimental_budgets`, keyed by `experiment_id`)
   is reserved atomically with the guard pass and is **never refunded** on a
   later submission failure — conservative, "no blind assumption of zero
   exposure."

4. **Submission-timeout-before-broker-id gap closed** — a NEW, distinct
   failure mode from the pre-existing Task 77I `UNCONFIRMED_TIMEOUT` (which
   applies only *after* a broker order id exists). `submit_order()` itself
   is now wrapped in try/except; on failure the intent is marked
   `SUBMIT_FAILED_UNCERTAIN` (visible to `_orphaned_uncertain_intents_for`,
   which feeds `_pending_quantity` and the `PENDING_ENTRY_EXISTS` guard, so a
   retry can never oversell/pyramid against a genuinely-unknown outcome) and
   the **original exception is re-raised unchanged** — see "Regression found
   and fixed" below for why this matters.

5. **Alerts and shadow tracking** (`notification_outbox.py`,
   `shadow_ledger.py`) — new `CLASSIFICATION_EXPERIMENTAL_BUY`/`_SELL`,
   structurally distinct from `CLASSIFICATION_ACTIONABLE_*`, with the
   required verbatim banner `EXPERIMENTAL_BANNER` prepended to every
   experimental message and the dedup key extended with `experimental_id` so
   two experiments (or an experimental vs. a normal decision) never collide.
   `ShadowLedger.consider_entry`'s gate is extended from
   `recommendation != BUY` to `recommendation not in (BUY, EXPERIMENTAL_BUY)`
   — both recommendations still gated on the same actionability bar, never
   on `paper_entry_enabled`/broker availability (Task 78I's own
   shadow-independence invariant, preserved and re-verified by
   `test_task78i_shadow_independence.py`).

6. **Wired into the real runtime decision loop**
   (`decision_engine.py::_handle_entry`/`_check_exit`, not a helper or
   test-only override) — `_experimental_permissions()` computes
   `experimental_buy_permitted`/`experimental_paper_permitted`/
   `experimental_id` fresh for every signal, gated first by
   `_signal_is_fresh()` (a new freshness check reusing the SAME
   `config.stale_seconds` threshold `session_runner.py` already applies to
   raw bar freshness — a signal older than that is never admitted to the
   experimental path even under a fully valid, otherwise-matching
   authorization). `OpenDecisionPosition.experimental`/`experimental_id`
   carry the origin forward so a position's protective exit stays correctly
   labelled regardless of whether the entry permission that created it has
   since expired (exits are never gated on entry permission — mirrors
   `paper_entry_enabled`'s own pre-existing exit-independence).

7. **`cli.py`** loads `ExperimentalAuthorization` via
   `load_experimental_authorization(config.state_dir /
   "experimental_authorization.json")` inside `runtime()`, passes it to both
   `PaperLifecycle` and every `DecisionEngine` construction (`start` and
   `supervise` commands). No file is ever created by this task; the only
   example shipped is the inactive template (see
   `inactive_configuration_example.json`).

8. **`strategy_version` binding fixed to a real identity** — `decide()`/
   `ExperimentalAuthorization` require a `strategy_version`, but
   `QuantConfig` has no such field. Rather than leaving it permanently
   unmatchable (see "Bug found and fixed" below), `decision_engine.py` now
   reuses `talonx_backtest.reproducibility.get_strategy_version()` — the
   SAME sha256[:12] fingerprint of the frozen strategy files
   (`talonx_quant/{strategy,indicators,config,session}.py`) the backtest
   reproducibility pipeline already computes and tests — rather than
   inventing a second, parallel, hand-maintained version tag.

9. **Observability** (`observability.py`) — `build_decision_status`'s
   execution-status join now recognises
   `ENTRY_ELIGIBLE_EXPERIMENTAL_PAPER` alongside `ENTRY_ELIGIBLE`, and
   `build_integrated_projection` gained an additive-only `"experimental"`
   section (decision/notification/shadow/paper-order counts), explicitly
   documented as **never folded into** `actionable_approved_count` or any
   other validated-strategy statistic.

## Bug found and fixed during implementation

`strategy_version=getattr(self.config, "strategy_version", "") or ""` would
have resolved to `""` for every real signal (no such config field exists),
while `load_experimental_authorization` requires the file's own
`strategy_version` to be **non-empty** — making every authored authorization
file permanently unmatchable (`WRONG_STRATEGY_VERSION` forever). Caught
before any test was written against the wiring; fixed by reusing
`get_strategy_version()` (see point 8 above) instead of inventing a
placeholder constant.

## Regression found and fixed during implementation

The Stage 2 submission-wrap fix (point 4 above) initially re-raised every
submission failure as `PaperGuardError`. `DecisionEngine._handle_entry` only
catches `PaperGuardError` — so this silently converted what used to be an
**uncaught raw transport exception** (Task 78I's own documented contract:
`test_task78i_stage5_rehearsal.py::test_05_broker_failure_does_not_block_alert_shadow`
proves a raw exception must propagate past `_handle_entry` to
`SessionRunner`'s own outer per-tick guard) into a silently-swallowed guard
rejection. Caught by re-running that pre-existing E2E rehearsal test (it was
not in the lifecycle-only regression set originally run against the Stage 2
change). Fixed by re-raising the **original** exception unchanged after
recording `SUBMIT_FAILED_UNCERTAIN` state, and updating the two Task 79E
tests that had (incorrectly) asserted `PaperGuardError` to assert the real
`RuntimeError` instead.

## What was explicitly NOT done

- No activation: no `experimental_authorization.json` exists anywhere in
  this repository; the feature is unreachable in every real deployment
  until an operator authors one.
- No promotion of `strategy_approval_status` to `APPROVED` anywhere.
- No relaxation of the existing PAPER-entry / production approval gate for
  any non-experimental decision (proven by the unchanged pass count of every
  pre-existing test file this task's diff touches).
- `DecisionEngine.positions` is not rehydrated from `lifecycle.state` on
  process restart — a **pre-existing** gap equally affecting normal
  `STRATEGY` and `EXPERIMENTAL` positions, not introduced or worsened by
  this task. Documented, not fixed — see `remaining_issues.md`.
