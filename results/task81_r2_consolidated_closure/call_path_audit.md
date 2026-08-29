# Task 81-R2 §7 — Affected production call-path audit

Compares every acceptance row against the actual code after the fixes.

## `reconcile()` — entry points (all reach the one coherent contract)

| Caller | Context | Uses the R2 contract? |
|---|---|---|
| `talonx_piv/session_runner.py:307` `_maybe_reconcile` | per-tick, bounded cadence during a live session | yes — calls `lifecycle.reconcile(now=now)`; only reads `result["matched"]` (unchanged) |
| `talonx_piv/eod_lifecycle.py:151` `run_eod_lifecycle` | scheduled EOD + manual `cli eod` | yes — reads `matched`, `broker_open_orders`, `broker_positions`, `incomplete_read`, `complete` (all still present); INCONCLUSIVE mapping unchanged |
| `talonx_piv/cli.py:271` | `start` command, before `DecisionEngine` construction | yes |
| `talonx_piv/supervisor.py:191` `step3_reconcile` | supervised startup sequence, before entries are accepted | yes |
| `talonx_piv/lifecycle_probe.py:76` | probe pre-check | yes — reads `matched` |
| `talonx_piv/lifecycle.py:1824` `eod_flatten` | test/legacy path | yes |

Inside `reconcile()` the order-resolution phase runs, in order:
`_resolve_unconfirmed_orders()` → `_promote_orphan_order_intents()` →
`_resolve_uncertain_submissions(now=now)` →
`_refresh_non_terminal_orders()` → forward `_verify_broker_order_row` over
`broker.open_orders()` → reverse `orders_missing_from_broker_list` check.

## One coherent validation contract

| Helper | Used by | Purpose |
|---|---|---|
| `_extract_order_update_fields(row)` | `_resolve_unconfirmed_orders` (1123), `_resolve_uncertain_submissions` (1311), `_refresh_non_terminal_orders` (1436) | parse a broker Order response into `(status, filled_qty, fill_price, filled_at, error)`; a non-None `error` (unrecognised status, malformed/negative filled_qty, malformed fill_price, non-dict) means the response is NOT applied to accounting |
| `_validate_broker_update(order, status, filled_qty, fill_price)` | top of `apply_broker_update` (783) — therefore **every** apply path: `poll_order_until_terminal`, all three resolution helpers, direct callers | reject unrecognised status / non-finite·boolean·negative filled_qty / invalid fill_price / `filled_qty > requested` BEFORE any mutation |
| `_verify_broker_order_row(row)` | `reconcile` forward pass (1688) | `OK` / `UNTRACKED` / `CONTRADICTION` / `MALFORMED` — resolves to exactly one durable intent by **both** broker id and client_order_id; conflicting ids, id/client mismatch, terminal-vs-open (incl. `filled`), symbol/side/requested-qty/cumulative-filled disagreement → `CONTRADICTION`; malformed required fields → `MALFORMED` → counted as an incomplete read |
| `_promote_orphan_order_intents()` | `reconcile` (1609) | orphan `ORDER_INTENT` (no recorded order) → `SUBMIT_FAILED_UNCERTAIN` so the audited discovery / adoption / `operator_resolve_uncertain_submission` machinery handles it |

## `apply_broker_update` callers — all now validated

- `poll_order_until_terminal` (live poll loop) — validated (guard at 783).
- `_resolve_unconfirmed_orders` / `_resolve_uncertain_submissions` /
  `_refresh_non_terminal_orders` — parse via `_extract_order_update_fields`
  first, then `apply_broker_update` validates again (defence in depth).
- `talonx_piv/decision_engine.py` — **does not** call `apply_broker_update`
  (grep-confirmed); it drives entries/exits only through
  `lifecycle.order_intent(...)`.
- Test callers — supply values directly; validation applies equally.

## `reconciliation_flags` consumers (durable BUY block)

- `talonx_piv/lifecycle.py:order_intent` BUY guard — `unexpected_short_detected`
  (highest priority) then `entry_admission_blocked`
  (`RECONCILIATION_BLOCKS_NEW_ENTRIES`), after the specific same-symbol
  guards (`ALREADY_HOLDING` / `PENDING_ENTRY_EXISTS`). SELL path, alerts,
  shadow, monitoring, `eod_flatten` / `run_eod_lifecycle` are **not**
  gated by it.
- Persisted in `lifecycle_state.json` (`LifecycleState.reconciliation_flags`,
  written by `_save`, read by `_load`) → survives a full process restart.

## Result-dict shape (backward compatible)

`reconcile()` still returns every key earlier callers read
(`matched`, `broker_open_orders`, `broker_positions`, `incomplete_read`,
`complete`, `consistent`, `untracked_broker_orders`,
`contradictory_broker_orders`, `unresolved_submissions`,
`unconfirmed_timeout_orders`, `orphan_intents`, `read_failures`, ...) plus
the new `orders_missing_from_broker_list`. No caller reads a removed key.

## Acceptance rows vs code — all satisfied

R2a.1–R2a.9, R3.1–R3.6, R4.1–R4.6 each map to a named symbol above and a
passing regression test in `acceptance_matrix.md`. §5 rows R5.1–R5.3 map
to `scripts/gen_sample_multi_trade_1m.py` + the marker removals
(`xfail_skip_closure.md`). §6 rows to `report_corrections.md`.
