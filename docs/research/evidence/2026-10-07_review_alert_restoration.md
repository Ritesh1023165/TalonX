# Research-review alerts restored, VR entry collection kept interrupted (2026-10-07)

**Status: `ACTIVATED; NATURAL DELIVERY NOT YET OBSERVED`.** Delivery was restored after the 2026-10-07 session had
closed. Promotions occur only in the regular session, so no natural opportunity could arise before this report. No
message was manufactured.

**Owner direction.** Telegram review alerts are independent of paper-trading admission. An alert is an unvalidated
item for human review, not a profitability claim and not an instruction to open a paper trade.

## Deployment boundaries

| Step | UTC | Europe/London | Evidence |
|---|---|---|---|
| Code `51f17c7` pushed and live checkout fast-forwarded from `81f815f` | 2026-10-07 ~22:40 | ~23:40 BST | git |
| VR entry control written: `results/vr_paper/entry_control.json`, boundary = the pause boundary **2026-10-07T11:25:41.846991Z** (12:25:41 BST) | 22:41 | 23:41 BST | file |
| VR tracker restarted by its documented script `results/ops_restore_20261004/tracker_vr.sh` (unchanged `--until 2026-10-16`). Old pids 16020/16832 → new **18688/21460** | 22:41:49 | 23:41:49 BST | process table |
| Deployed VR code proven on a **copy** of `vr_live.db`, live stores read-only: heartbeat `entry_control: BLOCKED`, boundary 11:25:41Z | 22:42 | 23:42 BST | scratch run |
| Promotion restoration boundary `delivery_boundary_utc` | **2026-10-07T22:42:55Z** | **23:42:55 BST** | control file |
| Promotion restart via `talonx_opportunity restart promotion` (supervisor), declaration #44, **STRATEGY_MATERIAL**; version 43545fad20c0 → **1fc8264f3c56**; pid 1748/20708 | 22:43:01 | 23:43:01 BST | `deployment_events` |
| Dashboard interpreter relaunched by its supervisor | ~22:44 | ~23:44 BST | :8787 HTTP 200 |

Both restarted components were each restarted once, by their documented procedures. No live lock was cleared. Nothing
else was restarted.

## VR_PAPER_V1: interruption now enforced in code

`talonx_paperperf/vr_live.py` reads `results/vr_paper/entry_control.json`:

- **Both arms.** Signals decided at or after the boundary never become trades. The cursor advances past them, so lifting
  the control later cannot replay them; the count is recorded in `meta entry_control_blocked:<window>`.
- **Pending rows.** No `PAPER_ENTRY_PENDING` row whose Signal is at or after the boundary can open.
- **Open positions.** OPEN positions are still managed through exit.
- **Fail-safe.** A malformed or invalid control (bad JSON, non-boolean, a naive or missing boundary) blocks **all** new
  entries and is reported in the heartbeat (`entry_control: MALFORMED_BLOCKING`, plus detail).
- **ACTIONABLE flatten rule.** A send at or after the session's flatten (15:50 ET, or the close on a half day) is
  `SENT_AFTER_FLATTEN`.
- **NVCT legacy row.** Trade `13babda614db1b23` (2026-09-30, ACTIONABLE) is left as a **legacy `PAPER_ENTRY_PENDING`**.
  The tracker only ticks the current UTC date's window, so it can never be selected again. It is not rewritten.

**State at deployment.**
- 0 OPEN positions in either arm.
- 0 trades created after the pause boundary.
- Segment registry, observations and the 2026-10-16 end date are unchanged.
- Restored review deliveries are `PROMOTED_SIGNAL` rows decided after the boundary, so VR refuses them.

## Restoration boundary (no replay)

- **Resumption requires an explicit boundary.** It needs `paused: false` + `delivery_mode: RESEARCH_REVIEW` + a
  timezone-aware `delivery_boundary_utc`. Otherwise the component stays paused (fail safe).
- **Only promotions queued at or after the boundary are enqueued.** Older queue rows become `PROMOTED_SHADOW /
  PRE_RESTORATION_RECORD_ONLY`.
- **Paused-period queue rows** (SHADOW mode) expire as `MODE_SWITCH_NO_CARRYOVER`.
- **The 89 paused-period promotions remain record-only.** They are terminal `PROMOTED_SHADOW / SIGNAL_DELIVERY_PAUSED`
  rows, and at most one promotion per candidate exists ever.
- **No catch-up scan.** The promotion event cursor is durable, so a restart continues from the paused process's
  position.
- **Outbox reconciliation at restoration.** 1,221 `PAPER_OPPORTUNITY` SENT (historical, untouched) and 0
  `RESEARCH_OPPORTUNITY`. 0 rows were created during the pause and 0 after the boundary. Copies taken before restoration
  are in `results/review_alerts_20261007/`.

## Exact message format (plain text; this example was rendered locally and not sent)

```
🔎 TALONX — RESEARCH OPPORTUNITY
⚠️ UNVALIDATED — not a buy instruction

🟢 EXAMPLE · BULLISH setup
⭐ Score 72.3
💵 Ref $12.50
🕒 Signal 14:05Z · REGULAR · data 13:49Z (age 16m)
⏱ Horizon INTRADAY / SAME_DAY
🧪 Policy OPPORTUNITY_PROMOTION_V1 (Opportunity Engine)
📉 Research verdict: NEGATIVE: this policy's evaluated paper results were negative after costs (VR replay 2026-09-28/29 net -0.61%; forward 2026-09-30 net -0.46%)

For review only · not a trade event · no order placed
```

- Missing data renders as `UNKNOWN`.
- Destination is the existing TRADE_EVENT (Signal) bot. Outbox `event_type` is `RESEARCH_OPPORTUNITY`, promotion reason
  `RESEARCH_REVIEW_ALERT`.
- Unchanged: promotion rules, thresholds, rate limit (3 per 5 minutes) and queue expiry.
- Not involved: paper admission, sizing, costs, outcome calculations, V2 and the Opportunity Engine universe.

## Dashboard (`:8787` → Opportunity → Notification lanes)

The promotion lane shows:
- `RESEARCH_REVIEW_DELIVERY_ENABLED (… since 2026-10-07T22:42:55Z)`;
- alert class `RESEARCH_REVIEW (not a trade event)`;
- the NEGATIVE / UNVALIDATED status;
- the delivery boundary;
- review rows separate from legacy rows;
- pre-restoration and paused counts.

The VR lane shows the configured `ENTRIES_BLOCKED since 11:25:41Z`. The tracker reports its loaded state at its next
in-session tick (2026-10-08 premarket). All lane counts equal their stores.

## Tests

- **New:** `tests/test_vr_entry_control_and_review_alerts.py`, 23 tests.
- **Updated, intended changes only:**
  - `test_promotion_signal_pause.py`: resumption now needs a boundary.
  - `test_opportunity_promotion.py::test_14`: the guard is now the Lab destination, not the word "RESEARCH" in message
    text.
  - `test_continuous_opportunity_engine.py::test_15b`: second allowed event type.
- **Affected regression set:** **713 passed, 21 failed**. The 21 are the **same set that fails on the untouched
  `556c62c` baseline** (Task 102/104/112/114/118a/131/ri3 inventory, preflight and fixture tests).
- **Freeze gate:** `frozen_release_ok(HEAD, a56ec8c)` is True.

## Observation

`results/review_alerts_20261007/observe.py` is a detached, read-only observer that snapshots every 5 minutes until
2026-10-08 15:00Z, into `observation.jsonl`. It records:
- outbox rows by type and state, with the first lines of new rows (label check);
- promotions after the boundary by reason;
- VR heartbeat `entry_control`, plus VR trades and open positions;
- component health and Lab sends.

**First snapshot (22:45Z):** 0 new outbox rows, 0 rows created during the pause, 0 VR trades since the pause, all
engine components RUNNING.

## Rollback (keeps VR blocked; never replays)

**Re-pause alerts.**
1. Set `"paused": true` in `results/opportunity/control/promotion_signal_delivery.json`.
2. Declare the change.
3. Run `python -m talonx_opportunity restart promotion`.

Any pending review rows become `EXPIRED / SUPPRESSED_POLICY_PAUSE` (both event types). Paused-period promotions stay
record-only.

**Code rollback.**
1. Re-pause first.
2. Check out `81f815f`.
3. Restart promotion and the dashboard.

Then:
- **Keep `results/vr_paper/entry_control.json` in place.** Old VR code ignores it, but old code also only ingests
  `PROMOTED_SIGNAL` rows, and none are produced while paused.
- **Do not restart VR on old code while review delivery is enabled.**

**Never** delete `entry_control.json` or edit the VR cursor. Signals blocked so far stay skipped.

## Unchanged and follow-ups

**Unchanged:** V2 universe and campaign (OPS-006 open), strategy thresholds, Opportunity Engine universe, ERM
(parked; guards and ledger untouched).

**Follow-ups, not done here:**
- **600-stock universe change:** separate decision.
- **DTU:** the collector endpoint is still 2026-10-08 00:15Z (01:15 BST). The final evaluation is not run here.
- **V2 forward tracker:** next run 2026-10-08 06:00Z; end 2026-10-31.
