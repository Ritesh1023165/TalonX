# Task 76S — Stage 2: `paper_entry_enabled` Migration

## Prior state
No per-ticker execution setting existed anywhere in this repository before this task
(`PivConfig.universe` is a flat `tuple[str, ...]` with no per-symbol attributes; confirmed by grep --
see `execution_path_inventory.md` Stage 0 item 5). Every symbol in the 35-symbol universe was
implicitly, uniformly "enabled" simply by being present in that tuple; there was no independent gate.

## New mechanism
`talonx_piv/execution_settings.py::PaperEntrySettings`, loaded from a JSON file
(`{state_dir}/paper_entry_settings.json`, mapping `"TICKER": true/false`) via
`load_paper_entry_settings(path)`.

## Migration rule (rule 4/5/6 of Task 76S Stage 2)
**No ticker is silently carried forward as enabled.** The loader is fail-closed in every ambiguous
case:
- File does not exist at all (the state immediately after this task ships, before any operator has
  created the file) → **every ticker disabled**.
- File exists but is not a JSON object → **every ticker disabled**.
- A ticker key is absent from the file → **that ticker disabled**.
- A ticker's value is present but is not the literal JSON boolean `true` (e.g. `"true"` the string,
  `1`, `null`) → **that ticker disabled**.

This is a deliberately conservative migration: the mere fact that a ticker was part of the old,
unrestricted 35-symbol universe grants it nothing under the new mechanism. An operator must explicitly
create `paper_entry_settings.json` and explicitly set a ticker to `true` before any PAPER entry can
occur for it — matching this task's own instruction not to silently enable entries during migration.

## What this setting does and does not affect (Stage 2 rules 1-3, verified in code)
- **Controls new PAPER entries only**: consulted in exactly one place, `PaperLifecycle.order_intent`'s
  `BUY_TO_OPEN` branch (`talonx_piv/lifecycle.py`). The `SELL_TO_CLOSE` branch never consults it at all.
- **Never changes alpha calculations or the recorded recommendation**:
  `talonx_piv/decision_contract.py::decide()` computes the identical `Recommendation` regardless of
  `paper_entry_enabled` — the setting can only downgrade `execution_status` from `ENTRY_ELIGIBLE` to
  `ENTRY_BLOCKED_PAPER_DISABLED` while the `recommendation` itself stays `BUY` (see
  `decision_contract.md`).
- **Never suppresses protective exits, EOD cleanup, or reconciliation**: `order_intent`'s
  `SELL_TO_CLOSE` branch, `PaperLifecycle.eod_flatten`, `eod_lifecycle.run_eod_lifecycle`, and
  `PaperLifecycle.reconcile` never read `self.paper_entry_settings` — verified by inspection (only one
  `self.paper_entry_settings` reference exists in `lifecycle.py`, inside the `BUY_TO_OPEN` branch) and
  by Stage 4's protective-exit regression evidence (an existing long is still fully manageable with the
  ticker's entry disabled).

## Toggling entry off while a position is already open (rule 7)
Disabling a ticker only prevents a **new** `BUY_TO_OPEN`. An existing `OPEN` position for that ticker
is tracked independently in `LifecycleState.positions`/`open_position_by_symbol`, which
`order_intent`'s `SELL_TO_CLOSE` branch reads directly — it has no dependency on
`paper_entry_settings`. Protection (stop/target monitoring in `decision_engine.py`, EOD flatten) is
therefore unaffected by disabling entries mid-position (see `protective_exit_evidence.json`).

## Broker failures are recorded honestly (rule 8)
"Exit permitted" (the boundary check passing) is not "exit completed": `order_intent` returning
successfully only means the SELL request reached `broker.submit_order`; the actual fill is a separate,
later event (`apply_broker_update`), and `PaperGuardError` from a broker-side rejection propagates to
the caller unchanged (`decision_engine.py`/`lifecycle_probe.py` both already catch this and emit
`BROKER_ERROR` rather than assuming success) — this task did not weaken or bypass that existing
honesty; it is unchanged.
