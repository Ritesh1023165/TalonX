# /ping preflight (structural + tests; no live process)
Owner: TalonX Signal / primary listener (`talonx_dispatch/telegram_listener.py`, `_discovery_v2_section`).
Reports (test-proven against the real V2 status file produced by a release-mode service): release mode, provider/feed/adjustment, provider contract + fingerprint,
market-data health, campaign id, account blocks, EXIT_UNRESOLVED, open positions, runtime state/heartbeat, V2 actionable outbox delivery counts.
It never presents stale csv as the release provider ("NOT the release contract ... not release-grade").
Tests: `tests/test_v2_final_release_acceptance.py::test_ping_*`, `tests/test_task132_ping_discovery_section.py`, `tests/test_telegram_ping_safety.py`, `tests/test_telegram_listener.py`.
The listener reads the status path through `talonx_ops.prospective.paths.V2_STATUS_PATH`, which now follows TALONX_V2_STATUS_PATH, so /ping reads the release campaign's status file.
