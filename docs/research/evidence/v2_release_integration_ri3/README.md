# RI-3 — Dashboard and Operator Integration

Verdict: **RI3_ACCEPTED_WITH_BOUNDED_FOLLOWUPS** (implementation assessment;
next step awaits gatekeeper review, not release authorization).

## 1. Repository state

- Repository: Ritesh1023165/TalonX.
- Required branch: `feature/task131-option-a-integration`.
- Starting SHA: `b67aa133a3343a8e16a3727e4b6a22f3e24b46ed`.
- Starting worktree: clean. HEAD exactly matched the handoff; no later commits
  to reconcile, no reset/rebase/stash, no use of main.
- Final commit/push SHA is supplied in the completion response; this evidence
  is part of that commit, so it does not embed its own self-referential hash.

## 2. Executive verdict

The existing Active V2 dashboard/API and local status command expose the
campaign, authoritative account state, reservations, obligations, intent
history, blocks/clearance, scoped reconciliation, runtime health and logical
notification destinations. No trading economics or strategy changed.

Bounded follow-ups: physical Telegram provisioning/controlled validation,
provider/feed qualification, an external outage watchdog, and validation of
any chat aliases during deployment. Unknown telemetry is explicitly unknown.
No follow-up is permission to launch or send in this task.

## 3. RI3-A map

See [OPERATOR_STATE_MAP.md](OPERATOR_STATE_MAP.md), written **before source
changes**. Existing architecture is retained: `DashboardReadModel` -> existing
section API -> `renderV2`; no new SPA, dashboard server or control plane.
`talonx_v2.dashboard_read` and `python -m talonx_v2.run --mode status` share the
new read-only projection. Existing primary `/ping` remains supported.

## 4. Campaign/account summary

`campaign` supplies strategy, strategy_version, execution_mode, campaign_id,
starting_cash_usd, allocation and provenance. No environment default or current
balance is substituted for unknown historical starting cash. Missing/legacy
identity is labelled `UNKNOWN_LEGACY`; a NULL historical seed remains NULL.
One ledger file remains one isolated account/campaign.

## 5. Capital, reservations and available capital

`portfolio.cash` is settled cash. Reservation = durable PENDING count times the
persisted campaign allocation cap, matching the accepted service reservation
mechanism. Available = settled cash minus reservations. Unknown allocation
makes reserved/available unknown, rather than assuming all cash is free.
Reservations are NOT subtracted from equity. Allocated cost includes OPEN and
EXIT_UNRESOLVED; occupied slots also include PENDING reservations. The frozen
V2 capacity is 20. No new sizing, debit, release or capital-reset path exists.

## 6. Positions and EXIT_UNRESOLVED

Separate OPEN, EXIT_UNRESOLVED and CLOSED groups. Unresolved positions retain
cost/capacity and appear in account health, details and operator attention.
The alternate V2 dashboard/EOD reader also exposes unresolved obligations.
Existing paper-performance equity remains PARTIAL when unresolved value is
unknown. No lifecycle transition was changed to improve presentation.

## 7. Pending, recovery and cutover

Durable intent rows include symbol, campaign, admission timestamp, persisted
status/detail, reservation and the real exchange-calendar Session-3 close
(from the accepted calendar helper). Future-session waiting, price recovery,
FILLED, EXPIRED_STALE and CANCELLED_CUTOVER are distinguishable. A PENDING row
past its deadline is labelled DEADLINE_PASSED_AWAITING_SERVICE and **retains
its reservation** until the writer changes it. Reading never expires it.
Cutover audit history is available in the operator API.

## 8. Blocks and clearance

The projection exposes active/cleared blocks, campaign/account, reason type,
detail, reference and timestamps; clearance attempts include operator, reason,
evidence, time and outcome. No dashboard clearance button exists. The UI
points to `python -m talonx_ops.prospective clear-block --help`; existing
explicit operator/reason/evidence and verification requirements are unchanged.
Reason-specific unsupported clearances remain refused by the existing workflow.

## 9. Reconciliation

Two distinct scopes:

- Current **read-only ledger arithmetic** uses persisted initial capital minus
  OPEN/unresolved entry cost plus persisted realized P&L; accepted $1 tolerance.
  States: HEALTHY, LEDGER_MISMATCH, CASH_DEFICIT or UNKNOWN. Outstanding unresolved
  obligations remain a separate count even when cash arithmetic balances.
- An existing `eod.json` can be selected via `TALONX_V2_RECONCILIATION_PATH`.
  Its campaign must match. All eight ledger assertions must pass to label the
  historical result HEALTHY. Missing assertions are UNKNOWN; missing evidence
  is NOT_RUN_OR_NOT_AVAILABLE. Timestamp/reference are shown; the result is
  explicitly historical. No old run is represented as a fresh reconciliation.

Future normal `prospective close` evidence gains `reconciled_at_utc`; RI-3 did
not invoke close or run a production reconciliation. No reconciliation table
or schema migration was introduced.

## 10. Realized P&L

Uses CLOSED positions' persisted `realized_pnl_usd`, whose accepted settlement
contract is exit net minus persisted entry total. A nonzero-entry/exit-fee test
proves the projection does not rebuild cost basis from current prices.
Unrealized marks/equity are separate; unavailable values are not invented.
The old blanket claim that V2 cannot model fees was corrected to describe
Package 4's persisted fee support and still-unqualified cost assumptions.

## 11. Telegram/operator delivery status

V2, Operations and Intelligence outboxes are read without constructing stores.
Each logical destination reports enabled/configured state, PENDING/SENT/FAILED/
EXPIRED/RETRY/HELD/AMBIGUOUS counts, last success/failure and source availability.
Intelligence's retrying rows retain its own PENDING state and expose failure
time; no incompatible outbox state migration. Missing sources are flagged.
Configuration metadata is explicitly the **observer process environment**,
which may differ from runtime configuration. Runtime activation is only trusted
with verified process identity and a fresh heartbeat. SENT history is evidence
of recorded delivery, not RI-3 validation of current physical destinations.
Raw tokens, chat IDs, payloads, transport references and exception text are
excluded from new notification metadata. Recursive redaction protects historic
Telegram URLs in other V2 operator fields.

## 12. Physical Telegram configuration contract

| Destination | Credentials | Activation | Current real state |
|---|---|---|---|
| TRADE_EVENT | `TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN`, `TALONX_NOTIFY_TRADE_EVENT_CHAT_ID` | V2 existing `--deliver --transport telegram`; Intelligence existing delivery/materiality/opt-in gates | Credentials UNKNOWN; no service activated by RI-3; real delivery validated NO |
| OPERATIONS | `TALONX_NOTIFY_OPERATIONS_BOT_TOKEN`, `TALONX_NOTIFY_OPERATIONS_CHAT_ID` | `TALONX_NOTIFY_OPERATIONS_ENABLED=1` wires the existing V2 tick worker and Intelligence operational producer | Credentials UNKNOWN; no service activated by RI-3; real delivery validated NO |
| RESEARCH | `TALONX_NOTIFY_RESEARCH_BOT_TOKEN`, `TALONX_NOTIFY_RESEARCH_CHAT_ID` | `TALONX_NOTIFY_RESEARCH_ENABLED=1`; otherwise OFF | Credentials UNKNOWN; default OFF YES; real delivery validated NO |

TRADE_EVENT/OPERATIONS retain RI-2's `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
legacy fallback. Supplying both dedicated pairs permits Bot/chat A and Bot/chat
B with no further code change. Shared chat detection never claims physical
separation merely because a token variable has a dedicated name. Partial
fallback is labelled LEGACY_OR_MIXED. Research has no primary fallback and a
configured Research chat equal to the effective primary chat is rejected.

`TALONX_NOTIFY_DB_PATH` selects the shared Operations outbox (default
`notifications.db`). All producer/worker processes must receive the same path.
Intelligence's existing `TALONX_INTEL_DELIVER_CARDS=1` and
`TALONX_INTEL_DRY_RUN_DELIVERY=0` remain required for real company-card delivery.
No values, credentials, .env changes, bots or messages were created here.

## 13. Intelligence/company developments

`TelegramSenderAdapter` resolves TRADE_EVENT after the existing approval,
materiality, freshness and opt-in gates. Those gates and event types are
unchanged. Poll/recovery/delivery degradation enqueues a generic OPERATIONS
incident when Operations is explicitly enabled; raw error text is not sent.

## 14. Health/Operations routing

V2 source/pricing degradation and Intelligence processing/input failures use
the existing durable Operations outbox and worker. Stable component/condition/
hour keys suppress repeats, including across restarts; health messages expire
after one hour so stale incidents cannot flood a later activation. A service
fixture drives three degraded ticks and produces exactly one event. Operations
send failures remain independent of paper execution. This is not an external
watchdog: a dead worker cannot report its own death.

## 15. Intraday/Research isolation

Original DispatchAgent's uninjected push transport is Research-only and OFF by
default. It cannot inherit primary credentials. A same-primary-chat Research
configuration is refused. The existing single primary command/Intelligence
reply listener is retained; `/ping` and Intelligence message correlation remain
available, while legacy numeric Original IDs and Experimental resolvers are
blocked from producing Research content on primary. Original details remain
available in the dashboard. Injected mock transports remain test seams.

## 16. Runtime/process health

New service status identifies PID **and process creation time**, preventing
stale/reused PIDs from proving RUNNING. Fresh heartbeat plus verified identity
is required; stopped, starting, degraded and unknown states remain distinct.
Legacy status files without identity are UNKNOWN, not claimed running.
Last heartbeat, successful source poll, data health and provider-degradation
indicator are visible. Last market event and Redis health are UNKNOWN in the
V2 projection when not produced there; the existing overview market/Redis
surface is retained. No provider was contacted to fill missing telemetry.

## 17. Operator attention

Account blocks, unresolved obligations, arithmetic failure, notification failure,
source degradation and stale heartbeat are summarized without recommendations.
An unresolved block and its matching unresolved obligation do not create two
attention items; their detailed evidence remains separately visible.

## 18. Read-only safety

`operator_read` opens SQLite with URI `mode=ro`, `query_only=ON`, and a read
transaction per database, then explicitly closes connections. No store
constructor, migration, cash seed, block clearance, expiry, settlement or
delivery occurs on reads. The status CLI returns before V2Store/V2Service
construction. The alternate V2 reader no longer uses writable store connections.
Tests replace writable constructors, store connections and Telegram send with
exceptions and compare full database dumps before/after repeated reads,
including the actual Active V2 backend.

## 19. End-to-end fixture

See [operator_fixture.json](operator_fixture.json) and
[operator_fixture.html](operator_fixture.html). All data is synthetic and
isolated. Actual paper entry/settlement methods produce:

| Field | Expected/observed |
|---|---:|
| Starting cash | 100,000 |
| Settled cash | 81,000 |
| Reserved capital | 10,000 |
| Available capital | 71,000 |
| Allocation cap | 10,000 |
| OPEN + unresolved cost | 20,000 |
| Occupied/reserved slots | 2 + 1 = 3 / 20 |
| Settled realized P&L | 1,000 |

One OPEN, one EXIT_UNRESOLVED, one CLOSED, one PENDING, plus terminal intent
history, an account block, a successful notification, retrying notification,
reconciliation and runtime state are asserted. A separate fixture proves
clearance history and historical reconciliation health/failure/unknown.
The actual shipped JavaScript is compiled and `renderV2` is executed in Node
against fixture data. This is a renderer check, not a browser screenshot or
production SPA launch.

## 20. Defects corrected

Hardcoded $300k capital and inception; reserved cash shown as available;
unresolved cost/capacity/detail omitted; incomplete block/intent/delivery views;
writable status construction; absent process identity; blanket no-fee wording;
Intelligence resolver bypass; absent bounded health producer; unwired live
Operations worker; direct Original-to-primary push/reply boundary.

## 21. Code/schema/config/docs

New: `talonx_ops/operator_read.py`, `tests/test_ri3_operator.py`, this bundle.
Modified: existing dashboard backend/HTML; alternate V2 dashboard/status/live
wiring; service status/health hook; notification resolver/producers; Intelligence
adapter/poll-loop hook; Original transport and reply boundary; paper-performance
reader; timestamp in existing EOD JSON; one obsolete fee assertion; product
requirements/operational findings. **No database schema change.** No strategy,
pricing, recovery, sizing or settlement implementation changes.

## 22. Tests and provenance

Exact PowerShell commands and final outputs: [TESTS.md](TESTS.md),
[tests_regression.txt](tests_regression.txt), [tests_ri3.txt](tests_ri3.txt),
[tests_reply_boundary.txt](tests_reply_boundary.txt).

Development failures were corrected, not labelled pre-existing: missing
allocation in the initial fixture; a stale fee-model assertion; and an editing
syntax error caught at collection. Windows sandbox temporary-directory ACL
errors required elevated isolated pytest execution; one approval-review attempt
was blocked by a usage-limit review-system failure and retried after user
continuation. No unresolved test failure is claimed as pre-existing.

## 23. Remaining release gaps

- Physical destination credentials are UNKNOWN, current delivery validation NO.
  Resolve chat aliases/provision bot membership in controlled release acceptance.
- No external watchdog; runtime cannot prove provider availability beyond its
  recorded observations. No invented Redis/market event telemetry.
- Historical EOD evidence is explicitly selected, campaign-checked and labelled
  historical; no automatic full-history search on every dashboard refresh.
- Research reply details are dashboard-only in the primary listener; no new
  Research poller was introduced.
- Full browser/device layout review remains a bounded UI follow-up; the existing
  renderer and scoped backend are tested, with no redesign.
- Provider qualification, final release acceptance, prior-research review and
  prospective paper validation remain separate gates.

## 24. Production safety

Initial `Get-CimInstance` process query was denied; `Get-Process` succeeded and
found no Python/Redis/TalonX process. Only test tooling was later executed.
No TalonX launch/restart/stop, provider/broker activation, real Telegram send,
production outbox drain, reconciliation write, schema migration or capital
mutation. `v2_lane.db` remained 69,632 bytes with mtime 2026-09-15 04:45:51 UTC;
SHA256 `10e6c542df213221db48278a6018b71656650325dd5585b344a14e3b2e16675e`.
An early default-path read created SQLite's empty WAL/shared-memory sidecars
beside the existing notifications DB; its main-file mtime stayed unchanged.
Later test commands explicitly redirect that optional read away from runtime
files. This is disclosed as a filesystem read artifact, not a ledger mutation.
No production store was instantiated by the RI-3 tests.

## 25. Research integrity

No profitability claims, strategy tuning, Session-10 exit change, numerical
cost calibration, research rerun or intraday promotion. V2 paper capital and
primary results remain isolated from Original/Research accounts.

## 26. Roadmap gate

RI-3 DASHBOARD/OPERATOR INTEGRATION: COMPLETE

SEPARATE TRADE/EVENT TELEGRAM DESTINATION:
CODE-CONFIGURABLE YES; REAL CREDENTIALS CONFIGURED UNKNOWN;
REAL DELIVERY VALIDATED NO.

SEPARATE OPERATIONS TELEGRAM DESTINATION:
CODE-CONFIGURABLE YES; REAL CREDENTIALS CONFIGURED UNKNOWN;
REAL DELIVERY VALIDATED NO.

RESEARCH TELEGRAM: DEFAULT OFF YES.

PROVIDER QUALIFICATION NOT COMPLETED.
V2 RELEASE ACCEPTANCE NOT COMPLETED.
PROSPECTIVE PAPER VALIDATION NOT STARTED.
NEXT STEP AWAITS GATEKEEPER REVIEW.

## 27. Commit/push

Only RI-3 implementation, scoped tests, product tracking and evidence are
included. Final SHA, clean-status result and push receipt are in the completion
response. Stop after commit/push; no later roadmap task is started.
