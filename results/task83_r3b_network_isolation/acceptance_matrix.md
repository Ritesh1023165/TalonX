# Task 83-R3B Acceptance Matrix

| Gate | Evidence | Result |
|---|---|---|
| Starting checkpoint | Branch `research/talonx-strategy-validation`; local and remote-tracking SHA both `b9d2889a7692f5000d1cc87eb4c0ce51e7db1b50` before commit | PASS |
| Explicit fake injection | Listener constructor accepts and retains the supplied factory; polling tests assert the exact fake and token argument | PASS |
| No eager real Bot capture | The production default is a deferred wrapper; explicit factories are selected at construction without constructing a Bot | PASS |
| Factory validation | Non-callable factories and values that are not async context managers fail before polling | PASS |
| Backlog and live polling isolation | Backlog drain, live `get_updates`, and fake-error retry remain on the injected fake | PASS |
| Disabled PIV | Disabled PIV constructs no Bot and starts no poller | PASS |
| Sole Original poller | Isolated Original/PIV coverage records one Original factory invocation and zero PIV invocations | PASS |
| Guard activation | Guard is opt-in and initialization failure is surfaced as a test usage failure | PASS |
| Fail-closed destinations | Unknown hostnames and non-loopback IPv4/IPv6 are blocked before their original DNS/socket operations | PASS |
| Loopback preservation | `127.0.0.0/8`, `::1`, and `localhost` are permitted for local tests | PASS |
| Deterministic report | Atomic JSON report separates expected blocks, unexpected attempts, permitted loopback events, and initialization failures | PASS |
| Negative-control reconciliation | Phase 1 declared four labels and observed each exactly once | PASS |
| Phase 1 focused tests | `73 passed in 7.31s`; exit code `0` | PASS |
| Phase 2 notification/collector tests | `89 passed in 7.61s`; exit code `0` | PASS |
| Unexpected external attempts | Phase 1 `0`; Phase 2 `0` | PASS |
| Guard initialization failures | Phase 1 `0`; Phase 2 `0` | PASS |
| Credentials and endpoints | Synthetic impossible token only; no valid credential or production endpoint added to committed R3B evidence | PASS |
| Runtime isolation | No Original, PIV, Redis, dashboard, broker, or external-service runtime was launched | PASS |
| Protected Quant files | No diff in `strategy.py`, `indicators.py`, `consumer.py`, or `config.py` | PASS |
| Historical evidence | No changes under Task 83-R1, R2, or R3A evidence | PASS |
| Required stashes | Task 56 stashes and Task 83-R2 stash preserved | PASS |
| Full-suite restriction | Full repository suite was not run | PASS |

Verdict: `TEST_ISOLATION_VERIFIED`
