# Cleanup / quarantine (TASK D) - provenance first, then minimal action
- Exported all 12 rows of the shared `notifications.db` with classification -> `notification_rows_before_cleanup.json`; file backup kept in gitignored `results/notifications.db.pre_cleanup_backup`.
- **The 9 fixture rows and the 2 canary rows are `SENT`: left in place unchanged** (history is not rewritten; dedup keys keep them idempotent; deleting is unnecessary for prevention).
- **Quarantined 1 row:** the canary's `SHUTDOWN` (event `7519bf86d1ca66910b556fa9`, campaign V2-PAPER-RC1) was `PENDING` (its drain process was already stopped). Marked `EXPIRED` with reason so no process draining the shared file can ever emit a late
  "SHUTDOWN" out of order. Nothing else was pending/retry. Final shared-outbox state: DEGRADED_HEALTH SENT 1, RECONCILIATION_FAILURE SENT 9, SHUTDOWN EXPIRED 1, STARTUP SENT 1.
- V2 trading ledgers untouched (legacy `v2_lane.db` md5 unchanged; RC1 ledger unchanged - see campaign verification). No valid RC1 notification was deleted.
