# Task 83-R3B Network-Isolation Verification Report

## Verdict

`TEST_ISOLATION_VERIFIED`

Task 83-R3B closes the R3A test-escape mechanism with explicit Telegram fake injection and an opt-in, fail-closed test network guard. The focused implementation and notification/collector phases both completed with exit code zero. No full-suite rerun was needed or performed.

## Starting checkpoint

- Branch: `research/talonx-strategy-validation`
- Starting local SHA: `b9d2889a7692f5000d1cc87eb4c0ce51e7db1b50`
- Starting remote-tracking SHA: `b9d2889a7692f5000d1cc87eb4c0ce51e7db1b50`
- Tracked tree before R3B: clean; R3B work was intentionally uncommitted at verification entry.
- No Python, pytest, or TalonX process was present before commit.
- Task 56 and Task 83-R2 stashes were preserved.

## Root cause carried from R3A

The escaped test constructed a listener before replacing the module-level Telegram Bot. A real constructor reference was therefore retained by the listener, and the later patch did not replace the stored factory. Entering the stored async Bot context could initialize a real Telegram client before the test fake controlled the boundary.

## Implementation design

`TelegramReplyListener` now has one explicit inbound Bot construction boundary. An explicitly supplied factory is retained exactly; production receives a deferred default wrapper that calls the real Bot only when a configured listener actually begins polling. Construction does not instantiate a Bot. Immediately before polling, the listener verifies that the factory is callable and returns an async context manager.

All polling tests inject factories during listener construction. Coverage proves exact-fake identity, patch-order independence, fake backlog drain, fake live polling, fake retry, no Bot construction for disabled PIV, and one Original poller with disabled PIV. No second listener or Telegram business-flow change was introduced. PIV remains notification-disabled unless explicitly configured through its existing boundary.

The pytest guard is activated only by the R3B guard switch. It patches synchronous socket connection and name-resolution boundaries plus common asyncio connection boundaries. It permits only `127.0.0.0/8`, `::1`, `localhost`, and non-IP local socket forms; all other IPs and unknown hostnames fail before the original DNS/socket operation. Missing patch targets fail initialization visibly. Reports are written atomically only to the explicit report path and independently track declared negative controls, observed labeled blocks, unexpected attempts, permitted loopback operations, and initialization failures.

## Changed-file inventory

Implementation checkpoint `db5f6b7` contains exactly:

- `talonx_dispatch/telegram_listener.py` — deferred default Bot factory, explicit injected-factory retention, and factory-interface validation.
- `tests/_network_guard.py` — reusable standard-library network guard and deterministic report/reconciliation contract.
- `tests/conftest.py` — opt-in pytest initialization, session fixture, reconciliation, reporting, and fail-visible setup.
- `tests/test_task83_r3b_network_isolation.py` — R3B injection, PIV, Original, network, report, initialization, and no-credential regressions.
- `tests/test_telegram_listener.py` — replaces module-global Bot patching with constructor injection and fail-fast handler fixtures.
- `tests/test_task83_r2_notification_session_integrity.py` — injects the existing local fake in the telemetry-write-failure polling case; no R2 historical evidence is changed.

This evidence checkpoint adds only:

- `results/task83_r3b_network_isolation/verification_report.md`
- `results/task83_r3b_network_isolation/acceptance_matrix.md`
- `results/task83_r3b_network_isolation/next_task_handoff.md`

The ignored `raw_test_output` directory contains execution artifacts for four preserved attempts. It is intentionally not committed because it includes verbose machine-local diagnostics and paths.

## Successful test evidence

Both phases were executed with `C:\workspace\TalonX\.venv\Scripts\python.exe`, bytecode writes disabled, the R3B guard enabled, an explicit fresh report, and a unique pytest base directory under `%TEMP%`. Standard output and error were redirected directly to separate durable files; each exit code was written separately. `Tee-Object` was not used.

### Phase 1 — guard and Telegram polling

- Successful run identifier: `20260830_102525`
- Result: `73 passed in 7.31s`
- Exit-code file: `0`
- Standard error: empty
- Guard initialized successfully: true
- Unexpected external attempts: 0
- Guard initialization failures: 0
- Declared expected negative controls: 4
- Observed expected negative-control blocks: 4
- Reconciliation: exact, one observation for each declared label
- Permitted loopback operations: 57

### Phase 2 — notification and collector

- Successful run identifier: `20260830_102552`
- Result: `89 passed in 7.61s`
- Exit-code file: `0`
- Standard error: empty
- Guard initialized successfully: true
- Unexpected external attempts: 0
- Guard initialization failures: 0
- Declared and observed negative controls: 0
- Reconciliation: exact
- Permitted loopback operations: 11

The successful reports contain only permitted loopback events and, for Phase 1, expected labeled blocks. They contain no successful or unguarded external attempt.

## Superseded diagnostic attempts

- `20260830_102245`, exit code 4: collection stopped on a Python 3.12 type-import compatibility error before tests ran. The guard initialized and recorded no unexpected attempt. The import was corrected. This is superseded diagnostic evidence, not a qualification run.
- `20260830_102347`, exit code 1: the intentionally fake token failed local shape validation before reaching the intended negative-control socket boundary, and sandbox permissions prevented pytest from cleaning its `%TEMP%` base directory. Three direct negative controls were blocked and no unexpected attempt was recorded. The token was replaced with a structurally valid but impossible synthetic value, and the authorized rerun used the same `%TEMP%` design with appropriate filesystem access. This is superseded diagnostic evidence, not a qualification failure.

Both attempts remain preserved and were not overwritten or deleted.

## Integrity hashes

Successful raw source artifacts, SHA-256:

- `telegram_guard_20260830_102525.stdout.log`: `c7902652e6a082609ed16f0d288534290ceb6df1d04d5e21ada745f62c002369`
- `telegram_guard_20260830_102525.exitcode.txt`: `13bf7b3039c63bf5a50491fa3cfd8eb4e699d1ba1436315aef9cbe5711530354`
- `telegram_guard_20260830_102525.network_guard.json`: `4687a9dcb265b20e491d83236d15963e05d3da49fde77b885a090b4e35e7c64d`
- `notification_collector_20260830_102552.stdout.log`: `3355c2de7cf2b169a9af1491a8788c5bc630104344c5a70b6d8b48e3556a73ac`
- `notification_collector_20260830_102552.exitcode.txt`: `13bf7b3039c63bf5a50491fa3cfd8eb4e699d1ba1436315aef9cbe5711530354`
- `notification_collector_20260830_102552.network_guard.json`: `a1cac9d623c6db4edb9eb0528dc5fcd9091d8ce5a72ff7663f618143797c2797`

Committed sanitized companion evidence, SHA-256 before evidence commit:

- `acceptance_matrix.md`: `d7d56bf75786579ed7c686d439b9f5f6672f067aacb709e0cb1c377a8042e365`
- `next_task_handoff.md`: `a804e4dc1ad9b914d6bc888cd6982ee4f0dd7546a7f786388fd7c32ffe945bb4`

The evidence commit protects this report and the complete three-file sanitized evidence set.

## Scope and safety confirmation

- No valid Telegram token, external credential, active configuration, or production endpoint is present in committed R3B evidence.
- No Telegram, Alpaca, Gemini, broker, Redis, dashboard, Original, or PIV runtime was launched.
- No order was submitted, no PAPER or experimental authorization was enabled, and no holdout was accessed.
- No strategy was tuned or approved.
- No historical Task 83-R1, R2, or R3A evidence was modified.
- Protected Quant files have no diff.
- Task 83-R3C was not started.
