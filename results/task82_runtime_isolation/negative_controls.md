# Task 82 Negative Controls

The focused Task 82 tests cover these fail-closed cases:

1. PIV resolves to Original's Redis endpoint/database.
2. A PIV Pub/Sub channel overlaps Original even when the Redis databases differ.
3. PIV channels do not all use the declared PIV namespace.
4. PIV channels are not mutually distinct.
5. PIV Quant persistence overlaps Original Quant persistence.
6. PIV Telegram is enabled while Original owns notifications and bot polling.
7. Original sees a duplicate Original process.
8. Original sees an unmarked PIV process.
9. PIV sees a duplicate PIV process.
10. PIV sees Original before PIV isolation has been verified.
11. Role-aware process enumeration returns malformed or unclassified output.
12. PIV runtime start/supervise omits the explicit `--isolated-parallel` marker.
13. Runtime bindings change across a restart but the session configuration hash does not change.
14. A recovery-required identity/exposure condition is masked by the new isolation marker check.

Positive controls prove one Original plus one marked, verified PIV is allowed,
the reused QuantScanner receives only PIV bindings, and PIV EventBus/outbox have
no Telegram adapter by default.
