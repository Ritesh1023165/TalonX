# Task 78I — Operator Runbook

This runbook documents commands only. **It does not authorise or recommend running a live
session.** Every real strategy remains `UNVALIDATED`; `paper_entry_settings.json` remains empty
by default (no ticker entry-enabled) unless an operator has explicitly and separately populated
it. This document is a reference for a future controlled-review session, not an instruction to
start one now.

## Startup

```
python -m talonx_piv.cli preflight --approved-sha <HEAD_SHA>
python -m talonx_piv.cli supervise --approved-sha <HEAD_SHA> --confirm-paper-session-start
```

`supervise` runs, in order: general preflight (`talonx_piv.preflight.Preflight`, including the
`no_duplicate_full_app_or_piv_process` check) → the 5-step startup-safety sequence (config →
execution ownership → broker-state reconciliation → data-readiness capability → strategy-
approval/PAPER-setting report) → `PAPER_SESSION_STARTED` → the live loop, wrapped in bounded
restart/backoff (`--max-restarts`, default 3; `--backoff-seconds`, default 30.0).

Optional flags: `--no-decision-path` (plumbing-only, no strategy evaluation), `--confirm-piv-
lifecycle-probe` (enables the operator-confirmed connectivity probe), `--no-telegram-inbound`.

Optional Gemini enrichment: set `TALONX_PIV_GEMINI_ENABLED=true` before invoking `supervise` (or
`start`) to attempt constructing the real chain via `talonx_brain.llm.build_research_chain()`.
Construction failure degrades to no enrichment — it never blocks `PAPER_SESSION_STARTED`.

## Status

```
python -m talonx_piv.cli preflight --approved-sha <HEAD_SHA>   # read-only, no ownership acquired
```

Read-only projections (no CLI subcommand needed — read directly, or via the dashboard route
below):
- `{state_dir}/component_health.json` — live component health snapshot.
- `{state_dir}/supervisor_recovery_state.json` — invocation/session history.
- `{state_dir}/latest_session_report.json` — end-of-session report (includes
  `integrated_projection` once `eod` has run).
- `dashboard_web.py` (start separately: `python dashboard_web.py [--port 8787] [--piv-state-dir
  <state_dir>]`), then `GET http://localhost:8787/piv/status` for the live integrated projection.

## Shutdown

```
python -m talonx_piv.cli kill-switch --cancel-paper-orders
```

Sets `kill_switch=True`/`session_enabled=False` (blocks new entries immediately) and, if
`--cancel-paper-orders` is given, cancels all open PAPER orders. The live loop observes the
kill-switch on its next tick, exits its own loop cleanly, and triggers the SAME guaranteed EOD
path a scheduled completion would (Task 72O) — no separate shutdown mechanism exists or is
needed.

## Recovery (after a crash or interrupted EOD)

```
python -m talonx_piv.cli eod
```

Identifies the ORIGINAL live session from `{state_dir}/session_identity.json` (never mints a new
session_id), re-runs `run_eod_lifecycle` — idempotent: a cancel/close already recorded as
requested for this exact session is not re-issued, but reconciliation always re-runs (a read-only
broker query, safe to repeat). Resolves any `UNCONFIRMED_TIMEOUT` order left by a crash via
`PaperLifecycle.reconcile()`'s own broker re-query before reporting a result.

## Cleanup (explicit, destructive — confirms first)

```
python -m talonx_piv.cli cleanup --confirm-paper-cleanup
```

Cancels all open PAPER orders and closes all PAPER positions unconditionally. Requires explicit
confirmation; acquires execution ownership first (fails closed if another process holds it).

## Execution ownership

Held automatically by `start`/`supervise`/`kill-switch`/`eod`/`cleanup` — no separate command.
Lock location: `%USERPROFILE%\.talonx_piv\locks\<sha256(endpoint|account_id)[:24]>.lock`
(overridable via `TALONX_PIV_LOCK_DIR` for testing only). A contended lock blocks the command with
`PIV_BLOCKED` (exit code 2) — there is no override/force flag. Resolve by confirming the other
process is genuinely still live (or has genuinely finished) before retrying.

## Environment variables referenced here
`TALONX_PIV_APPROVED_SHA` / `--approved-sha`, `TALONX_PIV_STATE_DIR`, `TALONX_PIV_LOCK_DIR`
(rehearsal/test only), `TALONX_PIV_GEMINI_ENABLED`, `TALONX_REDIS_URL`,
`APCA_API_KEY_ID`/`APCA_API_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
