# PAPER_SIGNAL promotion: Signal-bot delivery paused (2026-10-07)

**Classification:** owner-authorised **product-policy change**. This is not a strategy verdict. No results were
unblinded and no profitability was recomputed.

## Why

- `OPPORTUNITY_PROMOTION_V1` sent **878** `PAPER_OPPORTUNITY` messages to the Signal bot (`TRADE_EVENT`) in the
  sessions 2026-09-30 .. 2026-10-06 (174 / 203 / 177 / 191 / 133). It has sent **1,221** since 2026-09-25.
- Its latest accepted research status is negative: `INTRADAY_PREMISE_FAILURE_SUPPORTED / NO_EDGE_OBSERVED`.
  - VR replay 2026-09-28..29, CONTROL_VR_LIFECYCLE n=297: gross −0.094%, net −0.608%, PF 0.29.
  - Cost model: max(20 bps, measured entry spread).
  - Source: `2026-09-30_vr_paper_replay.md` (commit 5be6528).
  - Forward 2026-09-30 (n=156, net −0.463%): see `forward_alpha_validation.md`.
- The dashboard omitted these sends and stated that the Signal bot was "untouched by research".

Source: `C:\workspace\talonx_reviews\2026-10-07_product_status_review.md`.

## What changed

Code: commits `ab4b39d` and `bcfd10a` on `feature/continuous-opportunity-engine`, fast-forwarded from `556c62c`.

**Control.** The control file is `results/opportunity/control/promotion_signal_delivery.json` with `"paused": true`,
`policy_id PROMOTION_SIGNAL_DELIVERY_PAUSE_V1`.
- It is a file rather than an environment variable, because the engine supervisor respawns components with its own
  start-up environment. A file survives restart.
- A malformed file is treated as **PAUSED** (fail safe).

**Behaviour while paused.**
- With `TALONX_OPPORTUNITY_PROMOTION_MODE=PAPER_SIGNAL` and the control present, the promotion component runs
  record-only.
- Promotions are still evaluated, queued, rate-limited and recorded as `PROMOTED_SHADOW` with reason
  `SIGNAL_DELIVERY_PAUSED`.
- Paper outcomes are still tracked; that code path already covers SHADOW and SIGNAL.
- The Signal outbox is never drained.

**Unchanged.** Discovery, evaluators, the Lab notifier, outcomes, reporting, Sentinel, the V2 companion, Intelligence
and the VR tracker process. No strategy, threshold, universe or protocol changed.

**Runtime boundary.** `2026-10-07T11:25:41.846991Z` (12:25:41 BST).
- Recorded in `deployment_events` for `promotion` as `STRATEGY_MATERIAL`, version 2cb278644bc2 → 43545fad20c0,
  under declaration #43.
- Config fingerprint: `mode=PAPER_SIGNAL`, `signal_delivery=PAUSED`.
- The control file was written at `11:25:23Z`.

## Queue handling

**Already-pending notifications.**
- At start, every `PAPER_OPPORTUNITY` row in PENDING, RETRY or HELD becomes `EXPIRED`, with
  `last_error = "SUPPRESSED_POLICY_PAUSE: … ; was <state> after <n> transport attempt(s)"`.
- This is a policy disposition and is never labelled a transport failure.
- The step is idempotent, so a restart writes no duplicate records.
- At the live boundary **0** rows were pending. The outbox held 1,221 SENT rows only, so **0 were suppressed**.

**In-flight sends at the boundary.** The restart went through the engine supervisor's between-ticks stop, so no send
could be cut off mid-request. SENT and AMBIGUOUS rows are never modified.

**New promotions while paused.** They are recorded only. No outbox row is created.

**Resumption.** Resuming requires an explicit `"paused": false` plus a promotion restart, and an owner decision. On
resumption:
- suppressed rows stay EXPIRED;
- rows queued during the pause expire as `MODE_SWITCH_NO_CARRYOVER`;
- only promotions made after resumption can be sent.

There is therefore no replay burst.

**Preserved.** All 1,221 historical SENT rows are unchanged. The pre-pause outbox is backed up to
`results/promotion_pause_20261007/`.

## VR_PAPER_V1 impact

The registered population is OE PAPER_SIGNALs. The tracker reads `promotion.db` rows with
`state='PROMOTED_SIGNAL'`, and the ACTIONABLE entry time is the real Telegram `sent_at_utc`.

**ACTIONABLE arm: CLOSED at the boundary.** Real send times no longer exist for new signals. The tracker was not
changed:
- no delivery time is fabricated;
- no entry is backfilled;
- no promotion timestamp is substituted.

If a PROMOTED_SIGNAL row ever lacked a SENT row, the existing rule would skip it at the flatten
(`NEVER_SENT_BEFORE_FLATTEN`), which is covered by a test.

**VIRTUAL_REALTIME arm: INPUT INTERRUPTED.** This arm does not depend on timing, but its population is no longer
produced. Using paused `PROMOTED_SHADOW` promotions instead would change the population, which needs a separate owner
amendment. That was not done.

**Management continues.** The tracker process is untouched. No position was OPEN at the boundary; one 2026-09-30
ACTIONABLE `PAPER_ENTRY_PENDING` row predates this change and was left as it was.

**Segments.**
- `SEG2_DTU_V2` observations are the windows 2026-10-05 .. 2026-10-06. The last Signal-bot send was
  2026-10-06T19:55:30Z.
- The end date of 2026-10-16 and the segment definitions are unchanged, and the study is **not** extended.

**Records.**
- `results/vr_paper/ARM_INTERRUPTION_2026-10-07.json`.
- SEG2 status in `results/vr_paper/UNIVERSE_SEGMENTS.json`; the pre-pause copy is backed up.

## Dashboard (`:8787`, read-only)

**Notification lanes.** Opportunity → Notification lanes counts every lane from its own store and never merges lanes:

| Lane | Store |
|---|---|
| PAPER_SIGNAL promotion | promotion outbox |
| Intelligence cards | `ingestion_ledger.db` |
| V2 alerts | `v2_release_rc1.db` |
| Operations | `v2_release_rc1_notifications.db` |
| Lab | `opportunity_research_notifications.db` |
| VR paper | `vr_paper_notifications.db` |

- One notification is one row. Send attempts are shown separately.
- SENT (confirmed) is shown apart from AMBIGUOUS.
- History is kept separate from the period, which is the UTC day; the BST note is displayed.

**PAPER_SIGNAL card.** It shows:
- the mode: PAUSED (record-only), PAUSE_CONFIGURED_NOT_YET_LOADED, ACTIVE or UNKNOWN;
- the configured pause;
- promotion counts by state (all and period), separate from notification counts;
- promotions recorded while paused;
- historical sends;
- the **NEGATIVE** status ("Not a validated profitable strategy"), with verdict, evidence, cost model, source and as-of
  date.

**Other corrections.**
- The false "untouched by research" line is removed.
- The V2 "Logical Telegram destinations" counter now states its scope. `TRADE_EVENT` counts are V2 + Intelligence rows
  only and exclude the PAPER_SIGNAL lane; `RESEARCH` excludes Lab and VR.
- `operator_read.py` is not on the V2 freeze allowlist, so it was not modified. The labels are added in
  `dashboard_read.py`.

**Versions.** The dashboard shows:
- repo HEAD;
- tracked files that are dirty now;
- for each component: the loaded version, the checkout version recomputed with the same hash as
  `runtime.component_version` (source map parsed statically, with a drift-guard test), commit vs HEAD, and whether the
  tree was dirty at load.

A component is stale only when its **own** sources differ. Missing evidence shows UNKNOWN.

**Live reconciliation at 11:3xZ.** All six lanes' history counts equal their stores exactly:

| Lane | History |
|---|---|
| Promotion | SENT 1221 |
| Intelligence | SENT 354, AMBIGUOUS 3, PENDING 3, EXPIRED 50,843 |
| V2 | 0 |
| Operations | SENT 56, FAILED 1, EXPIRED 2 |
| Lab | SENT 2065 |
| VR | SENT 334 |

Promotion state counts equal `promotion.db`. All components show CURRENT, and no token-like strings appear in the API
output.

## Tests and gates

- `tests/test_promotion_signal_pause.py` has 19 tests, covering:
  - record-only while paused, with outcomes kept;
  - fail-safe on a malformed file;
  - suppression once, with SENT and AMBIGUOUS untouched;
  - no replay on restart or resumption;
  - unrelated destinations still dispatching;
  - VR keeping exits and taking no new entries;
  - no synthetic VR timestamps;
  - lane reconciliation, historical sends, and mode following the configuration;
  - removal of the false statement;
  - version attribution.
- The affected suites ran 687 passed, 21 failed. The **same 21 fail on the untouched `556c62c` baseline** (Task
  102/104/112/114 inventory, preflight and fixture tests). A second dashboard subset after `bcfd10a` ran 208 passed;
  its 3 failures are in that baseline set.
- `frozen_release_ok(HEAD, a56ec8c)` is True.

## Rollback

`results/promotion_pause_20261007/ROLLBACK_REFS.txt` records pre-deploy HEAD `556c62c` and promotion pid and version.

- **To lift only the pause:** set `"paused": false`, declare the change, and run `python -m talonx_opportunity restart
  promotion`. Nothing paused is replayed.
- **To revert the code:** check out `556c62c` and restart promotion and the dashboard. **First** confirm the outbox has
  no PENDING or RETRY rows, because old code would drain them. Code rollback does **not** reconnect VR: the interruption
  record stands, and any resumed arm needs a new owner decision.

## Bounded observation

Window: 11:32Z to 14:15Z, read-only, a snapshot every 2 minutes, 0 snapshot errors. It covers premarket and the
first 45 minutes of the regular session. Data: `results/promotion_pause_20261007/observation.jsonl`.

**Signal-bot promotion lane.**
- **0** outbox rows were created or sent after the boundary. The outbox is unchanged at SENT 1221; the last send was
  2026-10-06T19:55:30Z.
- **0** PROMOTED_SIGNAL rows after the boundary.

**Recording continues.**
- 11 `PROMOTED_SHADOW / SIGNAL_DELIVERY_PAUSED` promotions were recorded, plus 2 QUEUED under the rate limit, all
  with `signal_event_id` NULL.
- All 11 have paper-outcome rows; the total went from 1227 to 1238.

**Other components.**
- Discovery ran REGULAR scans every 5 minutes. All 11 engine components and the supervisor heartbeat throughout.
- Lab sent 87 messages after the boundary. Intelligence sent 1. Operations had no new events.
- VR heartbeat was live: 0 new signals, 0 new trades, nothing open to manage.

**Dashboard at 14:15Z.**
- Mode: `PAUSED (record-only…)`.
- Promotions in the period: PROMOTED_SHADOW 11, QUEUED 2; `recorded_while_paused` = 11.
- Notifications: history SENT 1221, period SENT 0. These equal the stores.

No synthetic messages or trades were sent.
