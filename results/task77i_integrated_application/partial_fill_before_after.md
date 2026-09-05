# Task 77I — Partial-Fill Accounting: Before / After

## Location
`talonx_piv/lifecycle.py::PaperLifecycle.apply_broker_update` (closing-sell branch).

## Before (the bug)

On the FIRST `partially_filled`/`filled` status transition for a closing sell order, the
closing branch:
1. Computed `gross_pnl` using the position's full original **entry_quantity**, not the
   quantity actually filled this update -- overstating P&L on any partial fill.
2. Unconditionally set `position["status"] = "CLOSED"` and deleted
   `open_position_by_symbol[symbol]` -- even though only PART of the position had actually
   sold (a `partially_filled` status, by definition, means more may still come).
3. Because `open_position_by_symbol[symbol]` was already deleted, a SECOND status transition
   on the SAME order (e.g. `partially_filled` -> `filled`, both non-terminal-to-terminal steps
   Alpaca reports as separate calls -- confirmed via `poll_order_until_terminal`'s
   once-per-distinct-status-value dispatch) fell through to the **open/BUY branch**, which:
   - fabricated a brand-new `positions[...]` entry with `status: "OPEN"` for what was actually
     a SELL fill,
   - emitted a spurious `POSITION_OPENED` event tagged from a sell,
   - left this phantom record permanently orphaned (never reachable via
     `open_position_by_symbol`, so never sellable again),
   - and would have shown up as a false-positive internal open position in `reconcile()`,
     risking a false `EOD_RECONCILIATION_FAILED`.

Task 76S's own Stage 5 boundary tests already discovered the FIRST-ORDER symptom of this (a
second sell attempt was safely rejected, just as the less-precise `SELL_WHILE_FLAT` instead of
an oversell) and explicitly disclosed the deeper accounting defect as out-of-scope follow-up
work (`remaining_integration_work.md` item 4) rather than silently working around it.

## After (this task's fix)

1. Alpaca's `filled_qty` is cumulative per order. `apply_broker_update` now captures the
   PREVIOUS stored `filled_qty` before overwriting it, and computes the INCREMENTAL amount that
   actually happened this specific update (`incremental_qty = filled_qty - previous_filled_qty`).
2. The position accumulates `exit_quantity` (total ever sold, across possibly more than one
   closing order) and `remaining_quantity` (`entry quantity - cumulative exit_quantity`).
   `gross_pnl`/`net_pnl` accumulate per-fill (`incremental_qty * (fill_price - entry_price)`),
   never the full entry quantity misapplied to a single fill's price.
3. The position is marked `CLOSED` and `open_position_by_symbol[symbol]` is only removed once
   `remaining_quantity <= 1e-9` -- a genuine partial fill leaves the position `OPEN` with a
   reduced `remaining_quantity`, so a SECOND status transition on the SAME order correctly
   re-attaches to the SAME position (no phantom record possible).
4. The open/BUY branch is now explicitly gated on `side == "buy"` -- structurally impossible
   for a sell fill to ever fabricate an `OPEN` position, even in a hypothetical anomalous/
   out-of-band broker-update scenario.
5. `order_intent`'s own SELL_TO_CLOSE guard now reads `remaining_quantity` (falling back to
   the full entry `quantity` when no closing fill has happened yet), so oversell/duplicate-sell
   protection is computed against what is actually still held, not a stale/prematurely-zeroed
   value.

## Proof
See `tests/test_task76s_broker_boundary.py::test_partial_fill_of_a_closing_sell_correctly_reduces_remaining_and_blocks_oversell`
and `::test_partial_fill_then_second_sell_for_true_remainder_fully_closes_position` -- the first
proves the position stays correctly `OPEN` with the right `remaining_quantity` after a partial
fill and correctly blocks an oversized follow-up sell; the second proves a correctly-sized
follow-up sell for the TRUE remainder succeeds and produces correct cumulative P&L across two
separate fills.

## Fields affected
`positions[*]` gained `exit_quantity` (cumulative) and `remaining_quantity` (both initialized
at open time too, for a position with no closing fills yet). No existing field's meaning
changed for a position that only ever receives a single, fully-filling closing order (the
overwhelmingly common case today, since `PIV_QUANTITY`/`PROBE_QUANTITY` are always fixed at
1.0) -- `gross_pnl`/`net_pnl`/`exit_price` end at the identical final value they always did in
that case; only the INTERMEDIATE state during a genuine multi-fill close is now correct.
