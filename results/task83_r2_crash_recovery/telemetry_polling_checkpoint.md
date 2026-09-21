# Task 83-R2 telemetry and polling checkpoint

Externally executed on Windows on 2026-08-29. Codex did not launch pytest for these qualifying runs.

## Qualification results

- Original concurrent-thread regression repeated 20 times: 20/20 runs passed, every exit code `0`.
- R2 notification/session/polling regressions: `18 passed in 2.92s`, exit code `0`.
- Scenario 27 diagnostic: `1 passed in 0.69s`, exit code `0`.
- Windows collector PID probe plus scenario 32 contention: `2 passed in 2.39s`, exit code `0`.
- Focused Task 83/R1/R2 set: `80 passed in 9.40s`, exit code `0`.

The focused set covers exact session/date partitioning, restart preservation, historical selection,
corrupt/wrong/ambiguous evidence, thread and process counter reconciliation, timeout and permission
failures, crash-released OS locks, real backlog/live `get_updates()` boundaries, disabled PIV,
Original no-op behavior, collector/archive behavior, and scenarios 21-33.

## Windows process-safety finding

Two interrupted focused runs exited `-1` at genuine subprocess-contention scenarios. The collector
PID liveness helper called `os.kill(pid, 0)` before its Windows fallback. On Windows that API is not
a safe Unix-style signal-zero probe. It was replaced with read-only `OpenProcess` plus
`GetExitCodeProcess`; the targeted regression proves the Windows path never calls `os.kill`.

## Boundaries

No TalonX runtime, Redis, dashboard, broker, Telegram, Gemini, PAPER session, or external service was
launched. Protected Quant files remain unchanged.
