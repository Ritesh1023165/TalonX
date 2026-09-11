# TalonX controlled paper-session activation — 2026-09-11

**Verdict: LIVE_PAPER_SESSION_STARTED.**

Release SHA `a540f40a2b9770a8cd7b90a1da06f3898be93bba`
(`research/talonx-strategy-validation`). V2 fingerprint `11107198c5b81237`
unchanged. Session started `2026-09-11T08:11:55Z`
(`results/prospective_2026-09-11/session.pids.json`).

Today's XNYS session (Friday 2026-09-11) confirmed a real trading day
(`talonx_v2.calendar.is_session`); regular hours 13:30–20:00 UTC. Activation
happened **pre-open** (08:11 UTC) — this is normal: the stack must be up and
ready before/at the open, not launched mid-session.

## A. Runbook corrections (committed before any startup action)

Commit `a540f40` reordered `deployment_candidate.md`
(preflight → backups → isolated backlog check → apply reviewed
migration+expiry to production → delivery configuration → startup →
acceptance → EOD → rollback — the prior order started the stack *before*
configuring delivery while that section's own text said the opposite) and
removed `rollback.md`'s stale routine "restore pre-activation databases"
instruction (superseded by
`docs/audits/task117_final_activation_corrections/rollback.md`, which
prefers compatible-code rollback). No application was running while these
docs were edited.

## B. Pre-flight verification

```
python -m talonx_ops.prospective preflight --expected-sha a540f40a2b9770a8cd7b90a1da06f3898be93bba
```
All 17 gates `[OK]`: repo head/tree, V1/V2 fingerprint, strategy version,
Redis reachable, no stale processes, required ports free, V2 ledger
continuity (never recreated), V2 env vars resolved, active profile V2, real
capital off, Experimental external override absent, heartbeat decoupled from
tick, Experimental external boundary blocked, Telegram logical owner,
dashboard V2 section present.

Pre-activation checks: no owned stack running (`status` → `v2_process_dead`,
`service_health: DOWN`); no `v2_lane.db.startlock`; ports 8787/8760/8770/8501
all closed; Redis `talonx-redis` up (healthy); `.env` carries
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / the 4 `TALONX_V2*` vars (key
names checked, values never printed); effective execution scope re-verified
today: `48 configured → 43 active → 39 covered` (same 4 exclusions: BABA,
BLSH, SKHY, SPCX — known non-SEC-filers).

## C. Backups (writers stopped, WAL checkpointed first)

`PRAGMA wal_checkpoint(TRUNCATE)` on `v2_lane.db`, then consistent copies to
`C:\Users\rites\talonx_activation_backups\` (outside any tracked directory):
`v2_lane.db.pre_activation_20260911T081030Z` (md5
`29e57dbcd1a567fbc4bb0e73efdba95f`, verified equal to the live file),
`v2_service_status.json.pre_activation_20260911T081030Z`,
`env.pre_activation_20260911T081030Z` (secrets — kept outside any tracked
path, never printed), `ingestion_ledger.db.pre_activation_20260911T081030Z`.

## D. Isolated backlog check, then production migration + expiry

Isolated disposable copy of `ingestion_ledger.db` checked at
`2026-09-11T08:10:55Z` using the real `text_events.accepted_at_utc`
event-time lookup (never `event_time_lookup=None`): **9,840 EXPIRED / 3
PENDING** (same 3 survivors as an earlier same-morning rehearsal — AFL, ORCL,
JPM DIGEST cards — recomputed fresh, not reused, and consistent because only
~1h had passed). Copy discarded.

With writers still stopped, the reviewed migration + expiry was then applied
to **production** `ingestion_ledger.db` at `2026-09-11T08:11:26Z`:
- Additive schema: `DeliveryOutbox` open added `attempt_id`,
  `in_flight_since_utc`, `transport_message_id` to `intelligence_delivery`
  (25 → 28 columns).
- `expire_stale`: **9,840 EXPIRED / 3 PENDING** (identical to the rehearsal —
  expected, ~35s later). Row count unchanged (9,843 → 9,843, **0 deleted**).
  **0** EXPIRED rows carry a `sent_at_utc` (none falsely marked SENT).
- Production `ingestion_ledger.db` md5 changed
  `2ae2105c6f51a4af4b3b80dc06e5f30f` → `7ce472ddb827fbe722628d107a81907f` —
  **expected** (schema + 9,840 state transitions were written); documented,
  not treated as an anomaly.
- Continuity verified against the §C snapshot: `v2_lane.db` cash $300,000,
  0 positions, 0 trades, the ABCL `07242bc857569f60` `SKIPPED_ENTRY_STALE`
  disposition — all preserved (V2Store migration is separately additive and
  was exercised for real at startup, §E).

No historical row was deleted; no timestamp was rewritten; EXPIRED is
terminal and audit-logged only.

## E. Delivery configuration + startup

Env vars exported in the **same shell** immediately before `prospective
start` (so the supervisor and its supervised `intelligence` child inherit
them via ordinary `env = dict(os.environ)` propagation):
```
TALONX_INTEL_DELIVER_CARDS=1
TALONX_INTEL_DRY_RUN_DELIVERY=0
TALONX_INTEL_DELIVER_PER_CYCLE=20
TALONX_INTEL_DELIVER_TIMEOUT_SECONDS=20
TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS=21600
TALONX_INTEL_DELIVER_AGE_CUTOFF=1
```
```
python -m talonx_ops.prospective start ^
  --expected-sha a540f40a2b9770a8cd7b90a1da06f3898be93bba ^
  --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 ^
  --pricing-mode composite-yf --execution-scope resolved-active-watchlist ^
  --deliver --transport telegram
```
**Result: startup verdict READY.** base stack alive, V2 companion alive,
checkpoint daemon alive, dashboard :8787 alive; session dir
`results/prospective_2026-09-11`.

Config propagation verified **directly on the live process** (not assumed):
```
psutil.Process(<intelligence child pid>).environ()
  TALONX_INTEL_DELIVER_CARDS = 1
  TALONX_INTEL_DRY_RUN_DELIVERY = 0
  TALONX_INTEL_DELIVER_PER_CYCLE = 20
  TALONX_INTEL_DELIVER_TIMEOUT_SECONDS = 20
  TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS = 21600
  TALONX_INTEL_DELIVER_AGE_CUTOFF = 1
```
confirmed on **both** the `.venv` shim (pid 12112) and the real re-exec'd
interpreter grandchild (pid 15652). No second manual Intelligence poller was
started.

## F. Connectivity-test send

One clearly labelled message sent through the official route
(`talonx_dispatch.telegram_client.TelegramClient.send(..., retry_ambiguous=False)`
— the same transport class Intelligence-card and V2-alert delivery use):

> "TalonX controlled paper-session connectivity test — no trading action."

| field | value |
|---|---|
| sent_at_utc | 2026-09-11T08:17:37Z |
| outcome | `API_ACKNOWLEDGED` |
| message_id | 721 |
| destination | Telegram chat ending `...7730` (matches the configured `.env` chat, never printed in full) |

**API acknowledgement only — human receipt is not asserted.** No blind retry
was performed or would have been (`retry_ambiguous=False`); an
ambiguous/timeout outcome would have been recorded as `AMBIGUOUS`, not
silently retried.

Separately, and *not* fabricated: the supervised Intelligence poll loop's
**normal, automatic** first delivery cycle (at `08:15:56Z`, its second poll
iteration) found 6 genuinely-fresh DIGEST cards and sent them as **one**
aggregated Telegram message, `message_id 720` — AFL, ORCL, JPM, AAPL, DELL,
MSFT. 10 other newly-enqueued IMMEDIATE/HIGH cards from the same cycle were
correctly judged **stale by event time** (their underlying SEC filings were
disseminated hours earlier, overnight, before this morning's catch-up poll
ingested them — 8.5h > the 6h IMMEDIATE cutoff) and EXPIRED without being
sent, exactly the "old filings enqueued today are not fresh" policy. **No
historical-alert flood, no false SENT, no duplicate delivery**: of 9,856
total historical + newly-ingested rows, exactly 6 were SENT (one message),
9,850 EXPIRED, 0 duplicated.

## G. Acceptance (§E checklist)

| requirement | result |
|---|---|
| Exactly one owned stack, V2 writer, supervised Intelligence producer | `session.pids.json`: supervisor 7196, V2 companion 1336, checkpoint daemon 23260; lock rebound to pid 1336 with a live `owner_token`; process count (14 python.exe) matches exactly 7 supervised/companion components × shim+interpreter pair; no duplicate `intelligence` process |
| Mandatory components + first-tick readiness | verdict READY; V2 tick=3 at capture time, heartbeat_age_s ≈ 2–26s throughout |
| Scope 39; 45-day lookback; composite-yf effective | dashboard `funnel.scope`: `execution_scope_enforced: true, execution_scope_count: 39, window_days: 45`; `pricing_mode: "composite-yf"` |
| Both Intelligence delivery gates enabled | verified on the live process env (§E) and by the real send (§F) |
| Official transport configured; Experimental external sends blocked | Telegram send/receive READY; `experimental_external_boundary: "BLOCKED -- structural (Task 100B Phase 6, 3-condition gate)"`, `experimental_external_eligible: false`, `experimental_live_external_sends: 0` |
| Source freshness distinguished from DB-read freshness | dashboard "Event source readiness" card (source ok / DB read age / upstream poll age) separate from the DB-row counts card |
| Ledger invariants green | cash $300,000, 0 open positions, 0 trades, ABCL stale disposition intact, `hard_invariant_breach: []` |
| No historical-alert flood / false SENT / duplicate delivery | §F |

A natural V2 trade did not occur during this check window (not required for
PASS; `business_activity: NO_OPPORTUNITIES`, `interpretation:
STRATEGY_SELECTIVE`). A natural Intelligence delivery **did** occur (§F) —
reported as observed, not invented.

Live `:8787` dashboard screenshots (this directory's `screenshots/`):
`LIVE_ACTIVATION_overview.png`, `LIVE_ACTIVATION_v2_active_strategy.png`,
`LIVE_ACTIVATION_intelligence.png`, `LIVE_ACTIVATION_paper_eod.png` — genuine
live data, not an isolated fixture.

## Verdict

**LIVE_PAPER_SESSION_STARTED.** No concrete gate failed; no cleanup was
required. The session is left running at frozen SHA `a540f40a2b9770a8cd7b90a1da06f3898be93bba`.
