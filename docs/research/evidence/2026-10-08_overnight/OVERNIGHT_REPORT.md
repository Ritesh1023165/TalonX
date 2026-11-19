# Overnight campaign report (2026-10-07 23:32Z → 2026-10-08 08:31Z; 00:32 → 09:31 BST)

**Baseline.**
- Branch `feature/continuous-opportunity-engine`; HEAD = origin = `037c76b` at the start, with no drift.
- `forward_alpha_validation.md` is byte-identical (MD5 `6fa1639c…`) throughout.
- Unrelated untracked files were untouched.

**Machine.** On AC power, battery 100%, Balanced scheme with AC sleep = never, user logged in at the console. No
settings were changed. Because the session could stay active, no scheduler task was registered. The one-off checkpoint
ran as a detached, read-only process.

Each workstream has its own status. None of these statuses implies profitable alerts or a completed validation.

| Workstream | Status |
|---|---|
| A. DTU | `PER_WINDOW_EVALUATIONS_COMPLETE; COLLECTOR_OVERRUN_NOT_STOPPED; STUDY_LEVEL_PROCEDURE_ABSENT` |
| B. Universe | `PREVIEW_ONLY_NOT_DEPLOYED` |
| C. Paper execution | `AUDITED_WITH_CHARACTERISATION_TESTS; NO_ACCOUNTING_CHANGE` |
| D. Alerts / VR / health | `CONTROLS_ACTIVE_AND_LIVE_CONFIRMED; NATURAL_DELIVERY_NOT_YET_DUE` |
| V2 forward | `2026-10-08 RUN SUCCESS (operational only; outcomes not opened)` |

## A. DTU (details: `dtu/CLOSEOUT.md`)

**The collector did not stop at 00:15Z.**
- `run_forever` has no end condition; the loop script checks the endpoint only before a relaunch.
- It was not killed.
- It was idle from 23:59Z, then started writing **out-of-study window 2026-10-08** at 08:00:41Z: 27 sweeps by
  08:29Z.

**Coverage.** Every window has a snapshot. Collection gaps are small except 10-05 (15 gaps, 111 minutes, mostly evening).

**Evaluations.**
- The 5 missing documented per-window finals (10-01, 10-02, 10-05, 10-06, 10-07) ran at 00:20–00:22Z, with exit 0
  and hashes recorded. The existing 09-29 and 09-30 finals were not rerun.
- All windows: 0 MISSED, `SHADOW_STATUS CONTINUE`, contract VERIFIED, harm CLEAR.
- **10-07 SIGNAL capture is 0/0** because promotions were paused that day.
- SEG1 and SEG2 are reported separately and never pooled.

**No study-level procedure or threshold exists.** No aggregate verdict was produced; an UNAPPROVED draft is in
CLOSEOUT.md.

## B. Universe (details: `universe/PROPOSAL.md`, `preview.json`, `membership_2026-10-08.csv`)

**Method.** Live `DTU_V2_LIVE_FLOOR` (fingerprint `65f3285f8181c552`). About 2,093 names qualify; the current
admissible set is the 1,200 core plus 893 event-eligible names. Top-N is exactly the existing `core_rank` (live ADV20
descending, tie-break by symbol), so no new rule is introduced.

**Results** (latest window 2026-10-08, input session 2026-10-07, built 00:02:39Z):

| Cap | ADV20 cutoff | Last selected |
|---|---|---|
| 500 | $256.5M | XP |
| 600 | $205.3M | PCVX |
| 700 | $172.7M | ANF |

- All caps fill, with 0 boundary ties.
- Turnover at 600 is 6–7 names per day.
- Sector is UNKNOWN (no metadata stored).

**Workload.** Steady state goes from about 1,460–1,530 fetched symbols in 8 batches to roughly 650–750 in about 4
batches. Protected names and V2's 39 stay fetched, which is why the monitored total stays above 600.

**Owner decisions:**
- the cap value;
- whether the event tier for ranks above N is removed or kept;
- the deployment window and segment label.

## C. Paper execution (details: `paper_execution_audit.md`, `tests/test_paper_execution_realism_audit.py`)

**Per lane:**

| Lane | What it actually is |
|---|---|
| Promotion `paper_outcomes` | **Gross markouts from the data-time reference price** (~15–20 min before the alert). They credit pre-alert moves; this is a measurement, not an achievable trade |
| VR | Causal virtual clock. VIRTUAL_REALTIME is a counterfactual entry; ACTIONABLE enters at the next bar after the real send. Gap stops fill at the open (correct); intrabar touches fill exactly at the level. No volume cap. Cost max(20 bps, entry spread) |
| Original | Entry at the alert's own price ± 2.5 bps. Exit on the tick close only. 0 trades ever |
| V2 | SIP daily open → close at +10, causal finality. **Zero fees and no spread** (frozen), whereas research is net of 20 bps. No fill-size cap. Unresolved exits are never favourable |

**Risk data:**
- **Volatility and liquidity** are observed.
- **Spread** is partial: research/VR and DTU only, not in Opportunity Engine features.
- **Halt/LULD** data is missing everywhere.
- **Manipulation** cannot be established from the available data, and no claim is made.

The prioritised improvements (at most five) are in the audit.

## D. Restored alerts, VR and health (08:30Z checkpoint: `morning_checkpoint.json`, late 15.6 s, `late_flag=false`)

**Review alerts.**
- Delivery is enabled: `RESEARCH_REVIEW`, boundary 2026-10-07T22:42:55Z, promotion pid 20708, version
  `1fc8264f3c56`.
- No replay: 0 outbox rows after the boundary, 0 created during the pause, legacy 1,221 SENT unchanged.
- 0 paused-period rows changed.
- 0 promotions after the boundary, as expected before regular hours.
- **Natural delivery is not yet due or observed.** Regular hours start at 13:30Z (14:30 BST). The existing observer
  `results/review_alerts_20261007/` runs until 15:00Z; no competing observer was created.

**VR.**
- **Live confirmation:** the deployed tracker's **own** heartbeat, first at 08:05:51Z and again at 08:29:52Z, reports
  `entry_control: BLOCKED`, boundary 11:25:41Z. This is distinct from last night's database-copy proof.
- 0 trades since the pause; 0 open positions (management path intact; tested).

**Dashboard.** All six lanes match their own stores (`dashboard_reconciliation_morning.json`). The VR lane shows
"ENTRY COLLECTION INTERRUPTED".

**Owners and health.**
- One logical owner each (shim + interpreter pairs): promotion, VR, DTU, V2, Intelligence, dashboard, forward runner.
- No new component errors since the restore; the only events are the restart's own START/STOP.
- Intelligence: 39/39 FRESH. V2: CURRENT, scope 39, 0 open. OPS-006 stays open.

## V2 forward (operational fields only)

- Run `20261008T060000Z-564665`: scheduled 06:00:00Z, started 06:00:00.25Z, ended 06:03:28Z, **SUCCESS**.
- All 5 stages SUCCESS with 0 retries.
- Cutoffs: filing date ≤ 2026-10-07, prices ≤ 2026-10-07.
- Artifact exists and is `validated: true`.
- **The artifact was not opened** and no log tails were read. The loop continues to its 2026-10-31 stop date.

## Commits

| Commit | Content |
|---|---|
| `bb283b7` | DTU closeout, universe preview, paper audit, characterisation tests |
| this report's commit | morning evidence |

Both are pushed to `feature/continuous-opportunity-engine`. The live checkout is fast-forwarded.

Code and input hashes:
- DTU evaluations: `dtu/closeout.jsonl`.
- Universe preview: read-only reads of `market.db`, snapshot versions in `preview.json`.

## Remaining owner decisions and next steps

1. **DTU:** stop the overrunning collector, which is writing out-of-study 2026-10-08 data. Then approve or amend the
   UNAPPROVED study-level procedure and its criteria, before any study verdict.
2. **Universe:** cap (600 vs 500/700), event tier for ranks above N, and deployment window. The proposal, tests and
   rollback are ready; nothing is deployed.
3. **Paper realism:** choose which of the five improvements to schedule. The first two (labelling markouts; showing
   V2 at research friction) are display-only.
4. **V2 OPS-006:** the population decision is still open.
5. **Today:** watch the observer for the first natural `RESEARCH_OPPORTUNITY` delivery after 13:30Z. Until one is seen,
   the status remains "activated; natural delivery not yet observed".
