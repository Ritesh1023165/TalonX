# Test isolation (TASK E)
Root cause: tests exercising `close._record_v2_reconciliation_blocks` used the cwd-relative default outbox. Fix = `tests/conftest.py::_isolate_ops_notification_store` (autouse): per-test temp outbox path + a construction guard against the repo-root shared/release outbox.
Regression tests: `tests/test_pre_full_day_cleanup.py::test_01` (the exact polluting flow leaves the real file's size/mtime untouched, the row goes to the temp store, direct construction raises even with the env var scrubbed),
`test_05` (stale rows in a shared-style store cannot drain from the release outbox), `test_06` (survives restart). Focused suites that previously polluted (package2, package4, ri2, ri3, task114) leave the shared `notifications.db` byte-identical.
