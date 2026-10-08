# DTU shadow collector: endpoint closeout (2026-10-08)

**Status: `PER_WINDOW_EVALUATIONS_COMPLETE; COLLECTOR_OVERRUN_NOT_STOPPED; STUDY_LEVEL_PROCEDURE_ABSENT`.**

This is an operational closeout, not a profitability verdict.

## Collector at the endpoint (2026-10-08T00:15Z = 01:15 BST)

**The collector process did not stop.**
- `results/ops_restore_20261004/tracker_dtu_collector.sh` enforces the endpoint only *before relaunching*
  `python -m talonx_shadow.dtu run`.
- `talonx_shadow/dtu.py::run_forever` has no end condition.
- The running process (pid 9400 → 17920, started 2026-10-04T20:52Z) therefore continues past the endpoint by design.

**It was not killed,** per the task rules.

**Data state.**
- The last sweep was at 2026-10-07T23:59:40Z (AFTER_HOURS end); the last EDGAR poll at 23:56:40Z.
- 0 sweeps after 00:15Z. Outside PREMARKET/REGULAR/AFTER_HOURS the collector is idle.
- Window 2026-10-07 is therefore complete and stable.
- **Overrun:** from the 2026-10-08 08:00Z premarket it will start writing window **2026-10-08**, which is outside both
  registered segments. That data is not part of the study and must not be pooled.
- **Owner action needed:** stop the collector (or authorise a stop) before 08:00Z if overrun data is unwanted.

## Collection coverage (sweeps per window; a full day is ~960 at 60 s, 08:00–24:00Z)

| Window | Segment | Sweeps | First–last (UTC) | Gaps > 3 min (count / minutes) |
|---|---|---|---|---|
| 2026-09-29 | pre-segment (shadow start day) | 909 | 08:51–23:59 | 0 / 0 |
| 2026-09-30 | SEG1_PROD_DTU_V1 | 960 | 08:00–23:59 | 0 / 0 |
| 2026-10-01 | SEG1_PROD_DTU_V1 | 959 | 08:00–23:59 | 0 / 0 |
| 2026-10-02 | SEG1_PROD_DTU_V1 | 950 | 08:00–23:59 | 2 / 8.1 |
| 2026-10-05 | SEG2_PROD_DTU_V2 | 864 | 08:00–23:59 | **15 / 110.9** (mostly 20:59Z onward) |
| 2026-10-06 | SEG2_PROD_DTU_V2 | 956 | 08:00–23:59 | 1 / 4.1 |
| 2026-10-07 | SEG2_PROD_DTU_V2 | 935 (to 23:36 at measurement; final 23:59) | 08:00–23:59 | 1 / 3.5 |

Each window has its collector-built snapshot (`shadow.db snapshots`). Data: `collection_gaps_pre_endpoint.json`.

## Per-window final evaluations (the documented `daily.sh final` run_eval)

`daily.sh` defines the per-window final at 00:20Z on the next day:
`dtu_eval W` + `verify_contract W` + `harm_check W`, with the same greps.

- **Already existing:** 09-29 and 09-30 (run on 2026-09-30 and 10-01). Not rerun.
- **Missing and now run** after the endpoint by `endpoint_closeout.sh`, starting 00:20:19Z: 10-01, 10-02, 10-05, 10-06,
  10-07.
- **Code:** HEAD `037c76b`; `talonx_shadow` tree `88f0aa2f`.
- **Exit codes:** `dtu_eval` exit 0 for all five.
- **Not run:** `daily.sh`'s snapshot-build step. That step is collection, every window already has its snapshot, and
  building 10-08 would be post-endpoint.
- Hashes are in `closeout.jsonl`. Outputs are `results/dtu_shadow/checkpoints/<W>_final.txt` and
  `results/dtu_shadow/eval/<W>.json` (gitignored; hashes recorded).

| Window | Segment | SETUP / SIGNAL / V2 / LAB capture (PROD protection) | MISSED | SHADOW_STATUS | Contract | Harm stop |
|---|---|---|---|---|---|---|
| 09-30 | SEG1 | 100 / 100 / 100 / 100% | 0 | CONTINUE | VERIFIED | CLEAR |
| 10-01 | SEG1 | 100 / 100 / 100 / 100% | 0 | CONTINUE | VERIFIED | CLEAR |
| 10-02 | SEG1 | 100 / 100 / 100 / 96.5% | 0 | CONTINUE | VERIFIED | CLEAR |
| 10-05 | SEG2 | 100 / 100 / 100 / 98.5% | 0 | CONTINUE | VERIFIED | CLEAR |
| 10-06 | SEG2 | 100 / 100 / 100 / 97.7% | 0 | CONTINUE | VERIFIED | CLEAR |
| 10-07 | SEG2 | 100 / **n/a (0/0)** / 100 / 99.4% | 0 | CONTINUE | VERIFIED | CLEAR |

- The POLICY-protection view (non-circular) is in each file. Its LAB capture is 95.7–100%; all others are unchanged.
- **10-07 SIGNAL_CAPTURE 0/0:** PAPER_SIGNAL promotion delivery was paused all day, so there were no
  `PROMOTED_SIGNAL` rows. This is a population change, not a capture result.
- **SEG2 caveat:** from 10-05, production ran DTU_V2. The shadow's own V1-definition population is unchanged, but its
  production-candidate protection input and every shadow-vs-production comparison changed. SEG1 and SEG2 are reported
  separately and **must not be pooled** (`UNIVERSE_SEGMENTS.json` rule).

## Study-level closeout: no approved procedure exists

**No committed study-level final procedure or acceptance threshold was found.** No aggregate score, pooling rule or
verdict was computed.

**Draft, labelled `UNAPPROVED`, not executed:**
1. Freeze inputs: stop the collector, then hash `shadow.db` and every `eval/*.json` and `*_final.txt`.
2. Per segment (SEG1, SEG2 separately; 09-29 excluded as the start day), report:
   - window count and collection gaps;
   - per-window capture ranges (min/max of SETUP, SIGNAL, V2, LAB) under both protection modes;
   - MISSED totals;
   - ONE/TWO_PLUS_LATE counts;
   - contract and harm status.
3. Pre-specify, *before* looking at the table, the criteria the owner wants (for example "MISSED = 0 in every window
   and harm CLEAR"). They do not exist today.
4. State the conclusion per segment only (no pooling), plus the explicit caveats: SEG2 protection input,
   SIGNAL 0/0 on 10-07, the 10-05 collection gap.

## Remaining owner decisions

- **(1)** Stop the overrunning collector (before the 08:00Z premarket, to avoid writing out-of-study 10-08 data).
- **(2)** Approve, amend or reject the draft study-level procedure, and its criteria.
