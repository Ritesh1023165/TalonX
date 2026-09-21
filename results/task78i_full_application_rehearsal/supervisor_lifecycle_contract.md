# Task 78I Stage 2 — Supervisor Lifecycle Contract

## Launcher
`talonx_piv/cli.py supervise` — a new subcommand alongside the EXISTING `start`/`kill-switch`/
`eod`/`cleanup`/`preflight`, reusing `talonx_piv.cli`'s own conventions (argparse subparsers,
`.env` loading, `runtime()`'s component construction) rather than inventing a second launcher
style. `start` itself is UNCHANGED (zero diff to its own branch) — `supervise` is additive.

## One authoritative path
`supervise` constructs exactly ONE `talonx_piv.decision_engine.DecisionEngine` and ONE
`SessionRunner`, identical to `start`'s own construction — never a duplicate consumer. Both
`start` and `supervise` share the SAME `no_duplicate_full_app_or_piv_process` guard (now also
run inside `talonx_piv.preflight.Preflight`, Stage 2's own addition — see
`architecture_and_ownership.md`) before any component is constructed.

## Startup sequence (exact required order)
1. **Verify configuration** — `Preflight(...).run()` (git SHA/tree, feed accessibility,
   Telegram, universe, runtime parity — the EXISTING, comprehensive check) PLUS
   `run_startup_sequence`'s own `verify_configuration` step (PAPER/non-real-capital/paper
   endpoint — belt-and-suspenders, not a replacement).
2. **Verify execution ownership** — `run_startup_sequence`'s `verify_execution_ownership` step
   (see `multiprocess_ownership_evidence.json`).
3. **Establish/reconcile account and order state** — `run_startup_sequence`'s
   `establish_and_reconcile_broker_state` step, calling `PaperLifecycle.reconcile()` (which also
   resolves any `UNCONFIRMED_TIMEOUT` order left from a prior crash — Task 77I) BEFORE
   `start_session` is ever called. An unexpected broker-side short blocks startup here.
4. **Establish data readiness** — confirms `SessionReadinessValidator` is wired; actual
   per-symbol readiness is established live, during the session (unchanged mechanism).
5. **Confirm strategy approval and ticker PAPER settings** — reports (never invents) the current
   `StrategyApprovalStatus` (always UNVALIDATED for a real decision) and which tickers have PAPER
   entry enabled.

Each step runs in order; a failure at any step stops the sequence immediately (later steps never
run, confirmed by `test_real_capital_config_fails_verify_configuration_and_stops_there`) and
`supervise` exits `PIV_BLOCKED` (code 2) — no partial startup ever reaches `start_session`.

## Session identity vs. invocation identity
One `SessionIdentity` (`session_id`/`trading_date_et`/`runtime_sha`/`config_hash`, from the
existing `session_identity.py`, unchanged) is used throughout a trading day, including across a
supervisor-triggered restart. A SEPARATE `invocation_id` (`supervisor.invocation_id()`, a fresh
UUID) is minted on every process start/restart attempt and recorded in
`supervisor_recovery_state.json` alongside the `session_id` it belongs to — multiple
`invocation_id`s can legitimately share one `session_id`.

## Component health classification
| Component | Required |
|---|---|
| `preflight` | required |
| `execution_ownership` | required |
| `session_runner` | required |
| `decision_engine` | required iff `decision_path_enabled` and not `--no-decision-path` |
| `telegram_inbound` | optional |

`ComponentHealthRegistry.overall()` is `FAILED` only if a REQUIRED component is `FAILED`;
an optional component `DEGRADED`/`FAILED` lowers `overall()` to `DEGRADED`, never `FAILED` —
matching "optional Gemini/notification/dashboard failure does not block decisions."

## Bounded restart/backoff
`supervisor.run_with_bounded_restart` wraps `run_session(runner, listener)` (unchanged). Because
`SessionRunner.run()` already guarantees EOD-safety before returning or raising (Task 72O), a
restart here always begins from an already-flattened, clean state — never mid-position. A clean
exit (scheduled EOD, controlled kill-switch shutdown) consumes zero restart attempts. Exhausting
`--max-restarts` (default 3, `--backoff-seconds` default 30.0) raises `TerminalSupervisorFailure`,
reported as `PIV_BLOCKED`.

## Persistent recovery state and health
`{state_dir}/supervisor_recovery_state.json` — append-only list of every invocation's startup
report, keyed by `session_id`. `{state_dir}/component_health.json` — the LATEST
`ComponentHealthRegistry` snapshot, rewritten on every heartbeat (including inside the run loop
via `on_heartbeat`).

## Session-scoped logging
Reused, not duplicated: `piv_events.jsonl` (via the existing `EventBus`) already stamps every row
with `session_id`/`trading_date_et` (Task 69Q Part 2) — this remains the one session-scoped log.

## Graceful shutdown
Unchanged: the existing kill-switch → `SessionRunner.run()`'s own loop-exit → guaranteed EOD
path (Task 72O). `supervise` adds no new shutdown mechanism, only wraps the same guaranteed path
in the restart/backoff/health-tracking layer described above.
