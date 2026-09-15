# Task 139 Evidence Index — Recovery After Host Restart and Readiness Close-out

**What happened**: an unplanned host restart interrupted the TalonX
development stack. Investigation (§1 of `recovery_evidence.md`)
confirmed a planned Windows OS-update restart (Event ID 1074,
TrustedInstaller, "Operating System: Upgrade (Planned)" ×3), completing
`2026-09-15T01:47:33Z`. No prior Task 139 work existed to recover — this
bundle documents fresh recovery + close-out work performed this session.

**Starting HEAD**: `0fe57f4` (verified clean, matched
`origin/feature/task131-option-a-integration` exactly). **Final HEAD**:
see the commit this README ships with.

## File index

| file | what it is |
|---|---|
| `recovery_evidence.md` | full narrative: restart-cause evidence, infrastructure/component restoration, runtime attribution, accounting reconciliation, real post-launch progress, inbound-reply check |
| `exit_classification.md` | full timestamp-by-timestamp classification of every historical "exited unexpectedly" supervisor-log entry against known documented restarts — corrects an overcautious Task 138 report passage |
| `post_recovery_checkpoint_capture.json` | full live `talonx_ops.prospective.checkpoint.capture()` output taken after the stack stabilized |
| `focused_test_run.txt` | the focused regression battery run for this task's one code change |

## Completed / pending checklist

- [x] Restart cause established with direct evidence (not inferred from process absence alone)
- [x] Actual HEAD/branch/worktree state inspected before any action
- [x] Persisted obligations (cash, positions, intents, cooldowns, both outboxes, IN_FLIGHT/AMBIGUOUS rows, enrichment backlog, last checkpoint, EOD record) captured and compared against the last available pre-restart snapshot
- [x] No database found missing; none recreated; no WAL/SHM deleted; no Redis flush
- [x] Stale V2 lock verified genuinely stale (dead PID, independently checked) before using the supported `break_stale` recovery path — never bypassed the live-owner check
- [x] Stack restored via the existing `prospective start` lifecycle command, with the actual verified HEAD, existing DB paths, and the previously authorized broad-discovery/durable-admission/Task 138 notification-policy/Telegram configuration
- [x] Current market-session boundary respected: no retrospective/backdated entries (positive evidence: V2's first tick correctly skipped 3 stale episodes); EOD confirmed `NOT_DUE_YET` and not run
- [x] Real post-launch progress verified (fresh enrichment rows, a successful V2 tick, dashboard 200 OK, Telegram send/receive ownership) — not just heartbeat/CPU
- [x] Accounting/reservation reconciliation: matching on every specifically-compared value (cash, position/intent/row counts, outbox state totals -- not a full database byte-for-byte comparison) before/after on both ledgers
- [x] Session/checkpoint continuity verified: fresh checkpoint daemon for the new session, campaign day counter correctly continued (not reset)
- [x] Historical Intelligence/Original "unexpected exit" pattern fully classified — separated cleanly from tonight's confirmed OS restart by exit-code signature and commit-timestamp correlation; zero remaining unexplained entries
- [x] Bounded diagnostic added (`talonx_ops/supervisor.py::_exit_code_hint`) — log-only, no control-flow change — so a future reviewer doesn't have to redo this classification by hand
- [x] Task 138 documentation inconsistency corrected (the overcautious "9 unexpected exits... flagged for operator attention" passage)
- [x] Natural inbound "details" reply checked via passive log evidence — still PENDING, not manufactured
- [x] Focused tests + adjacent regression battery run (68 passed, 0 failed)
- [ ] Live inbound Telegram reply verification — still PENDING (unchanged from Task 138; requires a natural operator reply)
- [ ] No live CONCISE-tier IMMEDIATE send observed since recovery (same honest limitation category as Task 138 — absence of a qualifying event is a valid outcome)

## Sanitization notes

No credentials, chat IDs, databases, bulk filings or binary archives
included. The exact recovery command is shown in `recovery_evidence.md`
§3 with secrets omitted (the bot token and any other secret reach child
processes via the existing, unmodified `.env`/environment-inheritance
path — never placed on a command line, never printed, verified reached
only indirectly via `telegram_send_ok: true`). Event IDs, commit SHAs,
PIDs and UTC timestamps preserved throughout as they carry no secrecy
and are necessary for verifiability.
