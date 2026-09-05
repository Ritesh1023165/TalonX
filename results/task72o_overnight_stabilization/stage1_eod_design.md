# Stage 1 -- Automatic EOD and Session Identity: Design

## Root problem
2026-08-26: live loop stopped normally 15:50 ET; broker reconciliation
only ran via manual `cli.py eod` at 16:57 ET, which built a FRESH
PivConfig/session identity independent of the live session -- EOD events
were stamped with a different session_id than the trading session they
reconciled.

## Fix
New module `talonx_piv/eod_lifecycle.py::run_eod_lifecycle()` is the
single source of truth for the EOD sequence, called from BOTH:
1. `SessionRunner.run()`'s guaranteed end-of-loop path (`_run_eod_lifecycle`),
   covering scheduled completion, controlled (kill-switch) shutdown,
   `stop_at`-driven recoverable termination, and a new outer
   `except Exception` that runs cleanup then re-raises (never swallows a
   real bug).
2. `cli.py`'s `eod` command (manual recovery), which now REQUIRES reading
   `session_identity.json` to identify the live session -- refuses (zero
   broker calls) if it cannot.

Both paths always pass the ORIGINAL live `session_id` (read from
`session_identity.json`, written by `cli.py`'s `start` before the runner
is ever constructed) and a freshly-generated `reconciliation_run_id`
(`stable_id("eodrun", session_id, trigger_reason, utcnow)`) -- never a
second trading session.

## Idempotency
`eod_state.json` (new, per `state_dir`) persists `session_id`,
`trading_date_et`, `cancel_close_requested`, `status`. A repeat call for
the SAME `session_id`+`trading_date_et` with `cancel_close_requested=True`
skips re-issuing `cancel_all_orders`/`close_all_positions`, but ALWAYS
re-runs `reconcile()` (read-only, safe). A state for a DIFFERENT
`trading_date_et` is never reused (treated as absent). Persisted BEFORE
reconciliation so a crash mid-reconciliation never re-issues cancel/close
on retry.

## Failure classification
- Cancel/close raises -> `INCONCLUSIVE`, `cancel_close_requested` left
  `False` (safe to retry both), no reconciliation attempted.
- `reconcile()` raises -> `INCONCLUSIVE`.
- `reconcile()` returns but `matched=False` or nonzero broker
  orders/positions -> `FAILED`.
- Only `matched=True` AND zero broker orders/positions -> `PASSED`.
- `SESSION_COMPLETED` emitted ONLY on `PASSED`.

## Scope
Diff limited to: `talonx_piv/eod_lifecycle.py` (new),
`talonx_piv/session_runner.py` (guaranteed trigger + trigger_reason
tracking), `talonx_piv/cli.py` (`eod` command rewired), `talonx_piv/events.py`
(7 new whitelisted event types). No protected file touched. No broker
mutation beyond the SAME `cancel_all_orders`/`close_all_positions`/
`positions`/`open_orders` calls already present in the pre-existing
`lifecycle.eod_flatten()`/`reconcile()`.
