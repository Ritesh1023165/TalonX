# Task 76S — Remaining Integration Work (deliberately not done in this task)

## 1. `decision_contract.py` is not yet wired into `decision_engine.py`'s live signal loop
`DecisionEngine._handle_entry`/`_check_exit` still make their BUY/SELL decisions with their own
existing, ad hoc logic (a BULLISH `QuantSignal` while flat opens; a stop/target cross while holding
exits) — they do not yet construct a `talonx_piv.decision_contract.Decision` record. This is
intentional: Stage 1's own instruction was to "produce a stable decision record later components can
consume," not to redesign the live signal-handling path in this same task. **Recommended follow-up**:
a small, separately-reviewed change that has `_handle_entry`/`_check_exit` call `decide(...)` first
(supplying `strategy_approval_status=StrategyApprovalStatus.UNVALIDATED` always, until a real approval
mechanism exists) and persist the resulting `Decision` alongside the existing event stream, without
changing what action is actually taken (which remains governed by the now-hardened
`PaperLifecycle.order_intent` boundary regardless).

## 2. No strategy-approval registry exists
`StrategyApprovalStatus.APPROVED` is exercised only in isolated test fixtures. There is still no
production mechanism to approve a strategy/version at all — this task did not invent one (per
instruction), so every real decision will resolve to `NO_TRADE`/`STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION`
once `decision_contract.py` IS wired in (item 1 above), until a separate task builds that registry.
This is a known, intentional consequence of "fail closed on unvalidated strategy," not a defect.

## 3. `paper_entry_settings.json` does not exist yet
`cli.py::runtime()` now loads it from `{state_dir}/paper_entry_settings.json`; since this file has
never existed before, **no ticker will be entry-enabled in production until an operator explicitly
creates it** (see `paper_setting_migration.md`). This is the intended, conservative migration posture,
but it does mean: without a follow-up operational step (creating and populating that file), the next
live PAPER session would see 100% of natural-strategy/probe BUY attempts rejected
`PAPER_ENTRY_DISABLED_FOR_TICKER`. This is disclosed here explicitly so it is not mistaken for a bug
during the next live session's own preflight review.

## 4. Partial-fill accounting on a closing SELL collapses straight to CLOSED
Discovered while writing Stage 5's boundary tests (`test_partial_fill_of_a_closing_sell_still_blocks_a_second_sell`):
`PaperLifecycle.apply_broker_update`'s existing (pre-Task-76S) fill-handling marks a position `CLOSED`
and removes it from `open_position_by_symbol` on the **first** partial fill of a SELL_TO_CLOSE order,
not only on a fill that fully covers the held quantity. A second sell attempt is therefore still safely
rejected (as `SELL_WHILE_FLAT` rather than the perhaps more descriptive `OVERSIZED_OR_DUPLICATE_SELL`),
so no unsafe behavior results — but the position/quantity bookkeeping itself does not currently
represent "partially closed, N shares still open." **This is a pre-existing characteristic of
`apply_broker_update`, not something this task modifies** (Stage 3's scope is `order_intent`'s
pre-submission validation, not `apply_broker_update`'s fill-application semantics) — flagged here as a
candidate for a future, separately-scoped fix if partial-quantity position tracking becomes important
(e.g. once position sizes are no longer always a fixed `PIV_QUANTITY = 1.0`).

## 5. No notifications, no shadow ledger
Per Stage 1's own instruction, this task implements neither. The `Decision` record (once wired in per
item 1) and the hardened `order_intent` rejection events (`PAPER_ORDER_REJECTED` with a `reason` field)
are the stable inputs a future notification/shadow-ledger task would consume — see this task's own
recommended next task (execution-independent alerts and shadow tracking).

## 6. Unexpected-short remediation
`reconcile()` now detects and blocks on an unexpected broker-side short, but per instruction, **no
automatic remediation exists** (it does not attempt to close/cover the short). An operator must
investigate and manually resolve it (e.g. via `cli.py cleanup`, which is broker-bulk-close and remains
untouched) before new entries can resume for any ticker.
