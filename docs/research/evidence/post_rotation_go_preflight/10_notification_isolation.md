# Notification isolation
Release outbox = v2_release_rc1_notifications.db (not created yet; created empty on first use). FOREIGN PENDING ROWS: 0; ep1 fixture rows: 0; stale pre-RC1 pending rows: 0; old SHUTDOWN row: none in the release outbox.
Shared notifications.db is NOT the release outbox (gate `release_notification_store` PASS): it holds the canary rows only (DEGRADED_HEALTH SENT 1, RECONCILIATION_FAILURE SENT 9, SHUTDOWN EXPIRED 1, STARTUP SENT 1), 0 pending/retry, byte-identical across the focused test runs.
