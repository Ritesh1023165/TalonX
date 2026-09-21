# SHUTDOWN pending (TASK M) - **BOUNDED_BUG** (not a release blocker)
`cmd_close` enqueues the SHUTDOWN notice AFTER `run_close` has already stopped the stack; the only OPERATIONS drain is inside that stack (V2 companion tick), so nothing remains to deliver it. The row stays durable and PENDING; on the next start it would have been
delivered as a stale message (out of order, "SHUTDOWN" of yesterday after "STARTUP" of today). Fix (tiny, safe): STARTUP/SHUTDOWN get `deliver_by` = +2 h so a stale one EXPIRES (test_15); the canary row was quarantined (EXPIRED). Consequence: a SHUTDOWN notice is
currently not delivered after a `close`; delivering it needs `close` to drain in-process before stopping - carried as a bounded follow-up (not redesigned).
