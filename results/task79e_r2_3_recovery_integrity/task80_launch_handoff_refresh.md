# Task 79E-R2-3 → Task 80 Handoff Refresh

This refresh supplements the existing Task 80 handoff chain. It does not
authorize a launch or experimental activation.

## Operational corrections

- Periodic reconciliation mismatch or failure now durably blocks new BUY
  exposure until a later successful matched reconciliation. Existing-position
  monitoring and SELL-to-close remain available.
- A same-day full-process restart reuses `session_id` only when lifecycle state
  is still live **and** config hash, feed mode, and runtime SHA are unchanged.
  A configuration change or new deployment mints a fresh identity; any
  session-scoped experimental authorization would require explicit re-authoring.
- Pending entries and partial BUY fills now preserve exact protective plans,
  actual remaining holdings, prior exits, and durable exit triggers across
  refresh/restart paths.
- Changed session bindings do not rewrite lifecycle state: experimental budget
  consumption and unresolved exposure remain durable and continue to block
  duplicate entry attempts.
- The post-audit full repository suite is clean at this task's working
  checkpoint: `2530 passed, 1 skipped, 10 xfailed` (zero failures).

## Unchanged boundaries

- Strategy status is still `UNVALIDATED`; profitability remains undetermined.
- Experimental permission is separate, absent, and disabled by default.
- Task 80 still requires separate operator authorization and fresh read-only
  preflight/broker/session checks. Do not infer launch approval from this task.
