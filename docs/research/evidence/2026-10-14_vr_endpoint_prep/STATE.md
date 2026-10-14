# VR_PAPER_V1 endpoint preparation: state and gaps (2026-10-14 ~12:10Z)

**Verdict: `ENDPOINT_READY` (stop enforced in code).** Two closeout **procedure gaps** need owner decisions. No runtime
correction is needed.

## Stop semantics

- `vr_live.main` stops by UTC date (`<= 2026-10-16`, inclusive).
- Collection on 10-16 runs 08:00Z–20:21Z; positions flatten at 19:50Z (15:50 ET).
- The child exits at about 2026-10-17 00:00–00:01Z.
- The wrapper does not loop, and no scheduler or supervisor relaunches it.

**Verified offline** (`tests/test_vr_endpoint.py`, 9 passed, plus 1 skipped in a worktree that lacks the machine-local
wrapper; its content was verified directly):
- The endpoint day is ticked only inside its calendar window, and the child exits at UTC midnight.
- A relaunch after expiry, including on the next Monday session, collects nothing.
- The default end date is 10-16.
- A slow tick crossing midnight cannot extend collection.
- The half-day bound comes from the calendar.
- Post-boundary Signals never open, while a pre-boundary open position is still managed to its `SESSION_CLOSE` exit.
- A legacy past-window pending row is never touched.
- A restart neither extends dates nor resets the block.

## Live state (operational metadata only; no returns, P&L or outcome summaries read)

- **Tracker:** one chain, `tracker_vr.sh` 18004 → 19580 → `vr_live` 18688/21460 (since 2026-10-07 22:41Z).
- **Heartbeat:** 12:04:27Z, entry control BLOCKED, 0/0 open.
- **Post-boundary activity:** 0 rows and 0 entries since 2026-10-07 11:25:41Z; 0 OPEN.
- **Row counts:**

  | Arm | EXITED | SKIPPED | PAPER_ENTRY_PENDING |
  |---|---|---|---|
  | ACTIONABLE | 133 | 729 | 1 |
  | VIRTUAL_REALTIME | 167 | 696 | 0 |

- **Pending row:** legacy NVCT (`13babda614db1b23`, window 2026-09-30, ACTIONABLE, never sent), unchanged since
  2026-09-30 20:03:48Z.
- **Segment labels:** `meta universe_segment` exists for 10-05 and 10-06 (DTU_V2). SEG1 windows predate the label and
  are defined by `UNIVERSE_SEGMENTS.json`.

## Closeout inventory (existence and provenance only)

| Window | Segment | `eod_<w>.json` | replay | `profitability/<w>.json` (replay input) | Status |
|---|---|---|---|---|---|
| 2026-09-30 | SEG1 | present | present | present | done |
| 2026-10-01, 10-02 | SEG1 | **missing** | missing | **absent** | observed |
| 2026-10-05, 10-06 | SEG2 | **missing** | missing | **absent** | observed |
| 2026-10-07 … 10-16 | SEG2 | — | — | — | INPUT_INTERRUPTED (not observations) |

## Procedure gaps (draft for review; nothing executed)

**G1. Replay inputs absent.**
- `eod_vr.sh` runs `vr_live eod` **and** `vr_replay`. Replay needs `results/profitability/<w>.json`, produced by the
  separate per-session `signal_forensics` / `eod_profit.sh` track, which was run only for 2026-09-30. Replay also fetches
  new bars.
- Proposal: at the endpoint run only `vr_live eod` for the four observed windows, and report replay as NOT AVAILABLE.
- Producing the forensic is a separate decision, because it computes Signal outcomes and fetches data.

**G2. No study-level procedure.**
- Only per-window EOD is registered: per arm, per DTU stratum, with a per-window delay effect. There is no pooled
  metric, threshold or verdict.
- Proposal: report per window and segment only, with the overall evidence marked partial or inconclusive by design.
- Any study-level summary needs a separately approved, pre-specified procedure that keeps segments and arms unpooled.

**G3. Owner authorisation.** Running the missing per-window EODs reads outcomes, so it must be authorised in the
endpoint task, after 2026-10-17 00:05Z.

## Unrelated work intact (metadata)

- **V2 forward:** next slot 2026-10-15 06:00Z, runner v1.2, calendar `a03cdf54…`, one loop chain. No V2 outcome
  opened.
- **PDM:** `verify_integrity` = []; collector task Ready (two triggers from 2026-10-20).
- **DTU / ERM:** no DTU or ERM process.
- **Review alerts:** enabled (`RESEARCH_REVIEW`). Universe schedule DTU_V3_TOP600 (from 2026-10-09) unchanged.
  Opportunity engine HEALTHY.
