# Task 83-R3B-R1 Root Cause

## R3C failure reference

Task 83-R3C Phase A passed 262 tests. The identical Phase B run stopped at 261 passed and one failed:

`tests/test_task83_browser_dashboard.py::test_existing_routes_unaffected`

The allowed in-process loopback request failed while the network guard was updating its evidence report. The dashboard route and production runtime were not defective.

## Confirmed concurrency defect

The original reporter rendered each snapshot to one shared sibling path named `.<report>.tmp`, then replaced the durable report. Concurrent permitted-loopback events could render different snapshots and write or replace that same temporary file concurrently. On Windows this produced `PermissionError`; a barrier-controlled pre-fix regression also proved a silent lost-update ordering in which a stale one-event payload replaced a newer two-event payload.

The first unique-temp repair removed writer-writer filename contention. Stress then exposed transient Windows sharing denial when replacing an existing destination that another thread briefly had open. This was the same report-writer boundary, not a network, dashboard, or production-service failure.

## Bounded repair

- A module-level in-process lock is keyed by normalized resolved report path.
- Writers acquire that lock before taking the snapshot, preventing stale snapshots from replacing newer state.
- Every write uses `tempfile.mkstemp` in the destination directory with a unique writer-owned filename.
- JSON is deterministically rendered, flushed, synchronized, and atomically replaced.
- Only transient `PermissionError` from atomic replacement is retried, using the same writer-owned file and a fixed bound. Persistent denial remains visible.
- All other failures remain immediate and visible.
- Failure cleanup removes only the current writer's unique file and never another writer's or an unrelated file.
- In-process readers use `read_report()` with the same path lock and see one complete previous or next report.

The implementation intentionally claims only in-process serialization. It does not claim cross-process writer or reader coordination.
