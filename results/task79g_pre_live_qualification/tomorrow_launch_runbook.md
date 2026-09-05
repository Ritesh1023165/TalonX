# Task 79G — Tomorrow's Launch Runbook

Prepared 2026-08-27 (evening, UK). **This is preparation only — nothing in this document has been
executed as a live session.** All commands below were inspected in `talonx_piv/cli.py`'s actual
`parser()` (re-read this task, current HEAD) — none are invented.

## 1. Target session date and verified exchange schedule

- Target trading date: **Friday, 2026-08-28**.
- Verified a **regular NYSE (XNYS) session** via TWO independent sources, cross-checked this task
  (see `external_readonly_checks.json`):
  - Local `exchange_calendars` package (XNYS): `is_session=True`, open `13:30:00Z`, close
    `20:00:00Z`.
  - Alpaca's own live `/v2/clock` and `/v2/calendar` endpoints: `next_open=2026-08-28T09:30:00-04:00`,
    `next_close=2026-08-28T16:00:00-04:00`; calendar entry `open=09:30, close=16:00`.
  - Both agree exactly: **09:30–16:00 ET = 13:30–20:00 UTC = 14:30–21:00 BST**. No early close, no
    holiday flag for this date.

## 2. Operator-handoff vs. market-start times (kept explicitly separate)

- **Operator handoff**: Friday 2026-08-28, ~08:00 **Europe/London**. This is when the operator
  intends to issue the Task 80 prompt — NOT a market time.
- **Market open**: Friday 2026-08-28, 09:30 ET = **14:30 Europe/London** — **6.5 hours after** the
  operator handoff. Task 80 will very likely begin during the US pre-market/overnight window, not
  at the open itself. Do not assume the market is open at handoff time.
- **Probe cutoff** (if authorised — see `probe_plan.md`): 15:00 ET = 20:00 BST, near the close.
- **EOD flatten**: 15:50 ET = 20:50 BST (existing, unchanged `config.eod_flatten_et`).

## 3. Final branch/SHA/configuration hashes

- Branch: `research/talonx-strategy-validation`.
- HEAD at the end of Task 79G's preparation: see `task79g_final_report.md` for the exact final
  SHA (this document is written before the closing commit; Task 80 must re-run `git rev-parse
  HEAD` fresh rather than trust this number).
- `config_hash`/`runtime_sha` are computed live by `talonx_piv.preflight.config_hash()` and
  `session_identity.build_session_identity()` at EVERY invocation — Task 80 will get its own,
  freshly computed values; none is pre-declared here.

## 4. Environment requirements

- Interpreter: `.venv/Scripts/python.exe` (the shell's default `python` resolves to an unrelated
  global install on this machine — see every prior task's own environment note).
- `.env` present at repo root with `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY`
  (verified this task: PAPER, ACTIVE, account `***YZF7`), `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
  (verified: bot `Talonxbot` reachable), `GEMINI_API_KEY` (verified: chain constructs), Redis
  reachable at `redis://localhost:6379/0` (verified: PONG, v7.0.15) — see
  `external_readonly_checks.json` for full detail and timestamps. **All of these must be
  RE-VERIFIED by Task 80 — this task's checks are a snapshot from the evening before, not proof
  of tomorrow's state.**

## 5. Exact authoritative supervisor command

```
.venv/Scripts/python.exe -m talonx_piv.cli supervise --approved-sha <FRESH_HEAD_SHA> --confirm-paper-session-start
```

This is the Task 78I-built unified supervisor (`cli.py supervise`), NOT the older `start` command
— it runs the ordered 5-step startup-safety sequence, component health tracking, and bounded
restart/backoff. Optional flags actually defined on this subcommand (from `cli.py`'s own
`parser()`, re-inspected this task):
- `--no-decision-path` — plumbing-only, no strategy evaluation at all.
- `--confirm-piv-lifecycle-probe` — enables the probe fallback (see `probe_plan.md`; also
  requires `paper_entry_settings.json` populated — see §7).
- `--no-telegram-inbound` — skip the inbound `/ping` listener.
- `--max-restarts <int>` (default 3), `--backoff-seconds <float>` (default 30.0).

**This task did not run this command.** Task 80 runs it, if and when the operator authorises.

## 6. Inactive configuration examples (NOT created by this task)

`paper_entry_settings.json` (does not exist today — natural entries and the probe both remain
blocked without it):
```json
{"AAPL": true}
```
Place at `{state_dir}/paper_entry_settings.json` — default `state_dir` is
`results/task64_paper_piv_readiness/runtime` (from `PivConfig.state_dir`'s own default, overridable
via `TALONX_PIV_STATE_DIR`). Creating this file is a Task 80 decision, not made here.

Gemini enrichment (off by default):
```
TALONX_PIV_GEMINI_ENABLED=true
```
Not set in this task's environment (confirmed — see `external_readonly_checks.json`).

## 7. Enabled/disabled matrix (current state, as verified this task)

| Component | State today | Activation requires |
|---|---|---|
| Market data (REST poll, Alpaca IEX) | available, not running | `supervise`/`start` |
| Quant (PIV's own `QuantScanner` instance) | available, not running | `--no-decision-path` NOT set |
| Gemini enrichment | **disabled** (`TALONX_PIV_GEMINI_ENABLED` unset) | operator sets env var before launch |
| Notifications (Telegram) | adapter reachable, no session running | any `supervise`/`start` invocation with configured token |
| Dashboard | not running | separate: `python dashboard_web.py [--piv-state-dir <dir>]` |
| Shadow tracking | wired, inert for real traffic (strategy `UNVALIDATED`) | requires an approval registry that does not exist — cannot be activated |
| Natural entries | **blocked** — `paper_entry_settings.json` absent AND `StrategyApprovalStatus` always `UNVALIDATED` | both would need to change; approval registry does not exist (out of scope) |
| Probes | **blocked** — `--confirm-piv-lifecycle-probe` not set AND `paper_entry_settings.json` absent | operator sets both, explicitly, on the day |
| Real capital | **structurally impossible** — `PaperGuardError` if `real_capital=True` or endpoint != paper | cannot be enabled short of editing `broker.py`'s own hardcoded `PAPER_ENDPOINT` |

## 8. Fresh Task 80 checks (this task's own snapshots do NOT substitute)

1. Account identity: re-run `broker.verify_paper_identity()` (or `cli.py preflight`) — confirm
   PAPER/ACTIVE fresh.
2. Broker orders/positions: re-query read-only — confirm still flat (or account for any change).
3. Process ownership: confirm no `{TALONX_PIV_LOCK_DIR}\*.lock` held by a live process; confirm no
   `run_talonx.py`/`talonx_piv.cli` process already running.
4. Current session identity: none should exist yet — `{state_dir}/session_identity.json`'s
   existence would indicate an unexpected prior/concurrent session.
5. Endpoint permissions: re-confirm `broker_endpoint`/`paper_trading`/`real_capital` resolve
   exactly as expected from the live environment (not assumed from this document).
6. Data readiness: cannot be pre-checked (it is a live, per-tick, per-symbol determination) —
   Task 80 observes it fresh once the session starts.

## 9. Observation-only vs. controlled-probe launch criteria

- **Observation-only** (recommended default): `supervise` WITHOUT
  `--confirm-piv-lifecycle-probe`, WITHOUT a populated `paper_entry_settings.json`. Market data,
  Quant evaluation, decision recording, and (if enabled) Gemini enrichment all run normally;
  **zero broker orders can be submitted** (every entry path fails closed on
  `PAPER_ENTRY_DISABLED_FOR_TICKER` or `STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION`).
- **Controlled probe** (requires explicit Task 80 / operator authorisation): additionally set
  `--confirm-piv-lifecycle-probe` AND create `paper_entry_settings.json` with `{"AAPL": true}` —
  see `probe_plan.md` for the full proposal, limits, and coverage matrix. **This task does not
  pre-authorise this — Task 80 must decide.**

## 10. Proposed exact probe limits (require Task 80 approval — see `probe_plan.md` in full)

Symbol `AAPL`, quantity `1.0` share, max 1 new entry, fires only after 15:00 ET AND only if no
natural order occurred first, closed by the runner or by guaranteed EOD flatten at 15:50 ET.

## 11. Monitoring intervals, critical alerts, graceful-stop procedure

- Poll interval: `SessionRunner`'s own default `poll_interval_seconds=60.0` (unchanged).
- Critical alerts to watch (via Telegram, if configured, or `piv_events.jsonl`/`/piv/status`):
  `BROKER_ERROR` (any reason), `EXECUTION_OWNERSHIP_ALREADY_HELD`, `UNEXPECTED_SHORT_BLOCKS_NEW_ENTRIES`,
  `EOD_RECONCILIATION_FAILED`.
- Graceful stop: `.venv/Scripts/python.exe -m talonx_piv.cli kill-switch --cancel-paper-orders`
  (sets `kill_switch=True`, cancels open orders if flagged) — the running loop observes this on
  its next tick and triggers the SAME guaranteed EOD path a scheduled completion would. **This
  task did not run this command.**

## 12. Automatic EOD and reconciliation recovery

EOD triggers automatically at 15:50 ET or on kill-switch/unhandled-exception (Task 72O,
unchanged) — idempotent, linked to the original `session_id`. If interrupted, manual recovery is
`cli.py eod` (see §13 — NOT run by this task, per its own hard boundary #3).

## 13. Manual recovery commands reserved for Task 80 (side effects noted, NOT run here)

- `.venv/Scripts/python.exe -m talonx_piv.cli eod` — **mutating**: cancels all open PAPER orders
  and closes all PAPER positions (via `cancel_all_orders`/`close_all_positions`), even if the
  account currently appears empty (the call itself is the mutation attempt, not conditional on
  there being anything to cancel/close). Requires identifying the live session via
  `session_identity.json`; refuses with `PIV_BLOCKED` if none exists.
- `.venv/Scripts/python.exe -m talonx_piv.cli kill-switch [--cancel-paper-orders]` — mutating if
  the flag is passed (cancels open orders); always sets the local kill-switch flag.
- `.venv/Scripts/python.exe -m talonx_piv.cli cleanup --confirm-paper-cleanup` — **mutating**:
  unconditional bulk cancel/close, requires explicit confirmation.

## 14. Post-session evidence collection

- `{state_dir}/latest_session_report.json` (includes `integrated_projection` once `eod` has run).
- `{state_dir}/latest_reconciliation.json`, `component_health.json`,
  `supervisor_recovery_state.json`.
- `{state_dir}/piv_events.jsonl` (append-only, full session log).
- If the dashboard was run: a `/piv/status` snapshot captured before shutdown.

## 15. Weekend research handoff

See `after_session_research_plan.md` — heavy research waits on the prerequisite gate documented
there (clean shutdown + resolved reconciliation), and is preparation-only in this task.
