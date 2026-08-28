# Task 80-P1 — Fail-closed duplicate-process safety gate

Date: 2026-08-28
Scope: production safety hardening and offline tests only. No session, broker mutation, network preflight, notification, experimental authorization, or holdout access occurred during implementation.

## Result

Task 80-P1 implementation is complete.

- Added one shared `talonx_core.process_guard.no_competing_talonx_process` gate.
- PIV preflight, supervised startup, and full-application preflight now use the same implementation.
- Process enumeration now blocks on access denial, timeout, missing PowerShell, subprocess failure, or malformed PID output.
- The PowerShell query forces normally non-terminating CIM errors to terminate, so an empty stdout stream cannot disguise `Access denied` as a successful empty process list.
- The current PID is excluded; any other `run_talonx.py` or `talonx_piv.cli` PID blocks startup.
- Candidate processes are restricted to Python executables, preventing a
  PowerShell invocation wrapper whose command text contains the child command
  from being misclassified as a second application pipeline.
- The independent per-account OS execution lock remains unchanged.
- No protected `talonx_quant` strategy file was changed.

## Verification actually performed

Focused offline selection:

```text
79 passed in 42.15s
```

Authoritative full suite:

```text
2546 passed, 1 skipped, 10 xfailed, 48 warnings in 925.84s (0:15:25)
0 failures
```

Launch-preflight follow-up found that a `powershell -Command ... talonx_piv.cli`
invocation wrapper was initially classified as a competing process. After
restricting candidates to Python executables, the focused correction suite
reported `19 passed in 16.98s` and the authoritative suite was rerun:

```text
2546 passed, 1 skipped, 10 xfailed, 48 warnings in 943.42s (0:15:43)
0 failures
```

The suite pass establishes regression/safety-test status only. It is not alpha evidence, strategy approval, profitability evidence, broker readiness, or launch authorization.

## Launch boundary after this fix

Strategy approval remains **UNVALIDATED** and prior development evaluation still produced zero eligible long trades. A same-day PAPER session requires all of the following after this code is checkpointed:

1. A fresh, preserved state directory rather than overwriting the stale 2026-08-26 runtime evidence.
2. Explicit per-ticker PAPER-entry settings. Experimental authorization remains absent.
3. Approved SHA bound to the new reviewed checkpoint.
4. Successful current duplicate-process enumeration.
5. Credentialed non-trading preflight proving PAPER identity, current orders/positions, feed, Redis, Telegram, runtime parity, and repository state.
6. Supervised PAPER-session authorization and EOD cancellation/flattening.

Real capital, short selling, options, leverage, experimental entry generation, and lifecycle probes remain disabled/out of scope.
