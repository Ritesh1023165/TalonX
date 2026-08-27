# Task 76S — Implementation Plan

## New files
1. `talonx_piv/decision_contract.py` — Stage 1. Typed `MarketView`, `Recommendation`,
   `StrategyApprovalStatus` enums; a frozen `Decision` record with every required field; a pure
   `decide(...)` function implementing the required behaviour table. No EventBus/Telegram/shadow-ledger
   dependency — a standalone module later components can consume (per the task's own instruction not
   to implement notifications/shadow-ledger here).
2. `talonx_piv/execution_settings.py` — Stage 2. `PaperEntrySettings` (a ticker -> bool mapping) +
   `load_paper_entry_settings(path)` loader. Fail-closed: a missing file, a missing ticker key, or a
   non-boolean-`True` value all resolve to **disabled**. Documented migration: this task introduces the
   concept fresh (no prior per-ticker setting existed) — the safe migration posture is that **no
   ticker is enabled until an operator explicitly populates the settings file**, not a blanket carry-
   forward of the old (unrestricted) behavior.
3. `tests/test_task76s_decision_contract.py`, `tests/test_task76s_execution_settings.py`,
   `tests/test_task76s_broker_boundary.py`, `tests/test_task76s_protective_exit_eod.py` — Stage 5.
4. A shared, autouse "no real broker mutation / no real notification" pytest guard, added inside the
   new task76s test files (monkeypatches `requests.api.request` and the Telegram sender's transport to
   raise immediately if a real network call is attempted) — a belt-and-suspenders check on top of the
   fake `Transport`/`EventBus(telegram=None)` pattern every existing PIV test already uses.

## Modified files
1. `talonx_piv/lifecycle.py` — Stage 3, the real enforcement point. `PaperLifecycle.order_intent` is
   the **only** caller of `broker.submit_order` and has exactly 4 callers itself (all inventoried in
   `execution_path_inventory.md`) — hardening it in place enforces every existing path with zero new
   call sites needed. Adds: an `ActionIntent` enum (`BUY_TO_OPEN`/`SELL_TO_CLOSE`) derived from the
   existing `side` string (anything else is rejected as `UNSUPPORTED_ACTION_INTENT`); an explicit
   `allowed_sources` allowlist (rejects e.g. a hypothetical `"BRAIN"`/`"GEMINI"` source as
   `UNAUTHORIZED_SOURCE`); a `paper_entry_settings` constructor parameter (optional, defaults to a
   fail-closed empty `PaperEntrySettings()`); non-finite/non-positive quantity rejection; BUY-path
   checks (already-holding → `ALREADY_HOLDING_NO_PYRAMIDING`, pending unresolved entry →
   `PENDING_ENTRY_EXISTS`, ticker disabled → `PAPER_ENTRY_DISABLED_FOR_TICKER`, unexpected-short flag
   set → `UNEXPECTED_SHORT_BLOCKS_NEW_ENTRIES`); SELL-path checks (flat → `SELL_WHILE_FLAT`,
   quantity exceeds `held − pending-sell-exposure` → `OVERSIZED_OR_DUPLICATE_SELL`). `reconcile()` is
   extended to detect a broker-reported short (`side == "short"` or negative `qty`) not matched by any
   internal OPEN long, persisting an `unexpected_short_detected` flag consumed by the BUY guard above —
   **no automatic remediation is added**, per instruction.
2. `talonx_piv/cli.py::runtime()` — one-line wiring: load `PaperEntrySettings` from
   `config.state_dir / "paper_entry_settings.json"` and pass it into `PaperLifecycle(...)`. This is the
   only production construction site; without this change the new gate would have no real-world effect.
3. Existing test files' local `lifecycle(...)` factory functions (one line each, not every individual
   test): `test_task64_piv.py`, `test_task65b_decision_engine.py`, `test_task65b_lifecycle_probe.py`,
   `test_task65b_warmup.py`, `test_task69q_evidence_upgrade.py`, and any other file whose factory
   constructs a `PaperLifecycle` and whose tests exercise a successful BUY — updated to pass an explicit
   `PaperEntrySettings` enabling that file's test symbol(s), preserving their original intent under the
   new fail-closed default. `test_task65_session_runner.py`, `test_task71s_*`, `test_task72o_eod_lifecycle.py`
   are checked and updated only if their own tests actually exercise a successful entry (many exercise
   only EOD/reconciliation/readiness paths that don't call `order_intent` with `"buy"` at all).

## What is explicitly NOT done in this task
- `decision_engine.py`'s live `_handle_entry`/`_check_exit` are **not** rewritten to consume
  `Decision` objects from `decision_contract.py` — that full wiring is deferred (see
  `remaining_integration_work.md`), consistent with Stage 1's own scope ("produce a stable decision
  record later components can consume").
- No notifications, no shadow ledger, no strategy-approval registry beyond the fail-closed default.
- No automatic remediation for a detected unexpected short.
- No change to `talonx_quant/{strategy,indicators,consumer,config}.py` or to the EOD reconciliation
  algorithm itself (`eod_lifecycle.py` is read, not modified).
