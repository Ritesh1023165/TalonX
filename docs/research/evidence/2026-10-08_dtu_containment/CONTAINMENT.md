# DTU shadow collector: overrun contained (2026-10-08)

**Status: `STOPPED_AND_CONTAINED`.** This is an owner decision under the registered study endpoint. No new evaluation
was run and no study-level score was computed.

## Identity and stop

The collector and its wrapper were verified by command line, process ancestry and study paths:

| Process | PIDs | Started |
|---|---|---|
| Wrapper `results/ops_restore_20261004/tracker_dtu_collector.sh` | 14504 / 15108 / 18524 | 2026-10-04T20:52:22Z |
| Collector `python -m talonx_shadow.dtu run` (shim → interpreter) | 9400 → 17920 | 2026-10-04T20:52:22Z |

No scheduled task or Startup entry relaunches either. No other script references the collector apart from evidence
scripts and the read-only verifiers.

**Stop.** There is no documented graceful stop. The collector's only writer is the sweep, which commits each sweep in
one transaction, so:
- I waited for sweep 6710 to commit (**10:36:19Z**);
- then terminated only the interpreter (**10:36:32.75Z**, 11:36:32 BST);
- the shim exited with it.

**Relaunch refused.** The wrapper's own loop then refused to relaunch, because the endpoint had passed:
`{"collector_loop_end": "2026-10-08T10:37:02Z"}`. No DTU process remains.

**Wrapper preserved.** The wrapper and task definitions are unchanged. The relaunch mechanism is self-disabled by its
endpoint check, and the collector now refuses on its own (below).

## Overrun extent

| | Value |
|---|---|
| Registered endpoint | **2026-10-08T00:15:00Z** (01:15 BST) |
| Last in-study sweep | 2026-10-07T23:59:40Z (window 2026-10-07 AFTER_HOURS) |
| Collector idle | 00:00–08:00Z (no phase) |
| Overrun collection | **2026-10-08T08:00:41Z → 10:36:19Z** (window **2026-10-08** only) |
| Final write | sweep 6710 at 10:36:19Z; collector stopped 10:36:32Z |

**Post-endpoint records.** These are preserved and excluded, with collection time separated from event time:

| Table | Excluded rows | Notes |
|---|---|---|
| sweeps | 154 | |
| verify | 3,286 | |
| promotions | 242 | |
| first_cross | 1,442 | event time `trade_utc` |
| edgar_8k | 22 | event time `updated_utc` |
| edgar_polls | 28 | |
| snapshots | 1 | `2026-10-08@2026-10-07` |
| snapshot rows | 14,391 | |

**Ambiguous** (collected before the endpoint, event after): **0**.

`exclusion_manifest.json` holds per-table ranges and keys. It is reproducible with `exclusion_manifest.py`, read-only.

**Files.**
- `shadow.db` sha256 `b312604b…0ebfa` (80,658,432 bytes; WAL not checkpointed by the read-only tool).
- `collector.log` ends with the stop and the loop-end line.
- Raw data is unchanged. `results/dtu_shadow/STUDY_CLOSED.json` records the closure.

**Write completeness.** Each sweep commits atomically, and the stop came 13 s after the last commit, so no partial
sweep exists. The `verify` sampler runs every 5th sweep; its last row is 10:33:19Z, which is consistent.

## Study evidence: preserved, not rerun

- Per-window finals for 09-29..10-07 (SEG1 `2026-09-30..10-02`, SEG2 `2026-10-05..10-07`) are unchanged. They were
  completed in `2026-10-08_overnight/dtu/`.
- Not rerun, not pooled, no study-level score.
- **"0 missed" is conditional** on the observed inputs and collection coverage. It assumes the production events that
  *were* observed, and the coverage of each window. Caveats:
  - 10-05 has 111 minutes of collection gaps;
  - 10-07 had **no Signal messages** (promotion delivery paused), so its Signal capture is 0/0;
  - SEG2's production-protection input changed with DTU_V2.

  It is not a statement about events the collector could not see.

## Expiry enforcement (code)

`talonx_shadow/dtu.py` now enforces `COLLECTION_END_UTC = 2026-10-08T00:15Z` in three places:
1. **Start:** `run` refuses (`REFUSED_STUDY_ENDED`).
2. **Before each sweep:** the loop stops (`STOPPED_AT_ENDPOINT`).
3. **After the snapshot fetch:** a sweep whose fetch finished after the endpoint writes nothing.

The wrapper's pre-relaunch check is unchanged. No automatic restart was added.

**Tests:** `tests/test_dtu_expiry_labels_top600.py`, part A, with fixtures only. The study was not restarted.
