# Task 83-R3B narrow handoff

## Scope

Task 83-R3B is strictly:

> Network-isolated Telegram polling tests with explicit fake injection and a fail-closed
> non-loopback network guard.

Do not reopen Task 83-R2 telemetry partitioning, rehearsal evidence, dashboards, runtime ownership,
Quant strategy behavior, brokers, or unrelated implementation findings.

## Required design

1. Every test that can call `TelegramReplyListener.run()` or enter a Telegram `Bot` context must
   inject an explicit bot factory at listener construction. Do not depend solely on patch timing or
   a mutable module symbol.
2. Install a test-scoped, fail-closed network guard before listener construction. It must reject
   non-loopback socket connection attempts and HTTP transports, including attempts during async
   context initialization. Loopback may be allowed only where a test explicitly requires it.
3. The guard must fail the test immediately with the attempted destination and call site, while
   excluding credentials, complete URLs containing tokens, and account identifiers from output.
4. Add a negative control proving that a deliberately un-injected production Bot path is stopped by
   the guard before any non-loopback operation can occur.
5. Add positive controls proving that explicit fakes exercise backlog drain, live `get_updates`,
   retry telemetry, listener stop, and exception paths without touching a real transport.
6. Bound each async listener test with an independent timeout so a missing fake stop cannot become
   an indefinite retry loop.
7. Assert the injected factory was called, the fake context was entered/exited, and every expected
   fake `get_updates` call occurred before accepting the test result.

## Acceptance boundary

- No external request can leave the process even if fake injection regresses.
- Production and test credentials are neither loaded nor printed.
- No Telegram listener, TalonX runtime, Redis, dashboard, broker, Alpaca, or Gemini service is
  launched.
- The exact legacy node
  `tests/test_telegram_listener.py::test_poll_forever_drains_backlog_then_handles_new_updates` is
  covered under explicit injection and the network guard.
- R3B produces its own bounded qualification evidence; it must not edit the R3A reports or claim to
  remove the historical R2 uncertainty.

## R3A fact to preserve

R3A established a local `getMe` request-operation attempt with a test placeholder, but could not
establish packet egress or Telegram receipt. R3B prevents recurrence; it cannot retroactively prove
what happened at the historical network boundary.

Do not implement R3B as part of R3A.
