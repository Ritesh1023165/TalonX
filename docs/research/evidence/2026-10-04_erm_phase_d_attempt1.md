# EVENT_RESPONSE_MAP_V1: Phase D attempt 1 (append-only evidence note)

**Outcome:** NO OUTPUTS, NO MARKER. The single scoring pass did not complete, so under the protocol (§6 note, lock rev 3.1) **one re-execution remains allowed**.

| | |
|---|---|
| Lock | revision 3.1, fingerprint `ad68792d18c67a7f201af3f4a5b0e3565a26759c7e8c904bc035c48e327a7bd2` |
| Runner commit | `53eb2da` |
| Scheduled task | `\TalonX\ERM_V1_PhaseD_2026-10-03` (S4U), 8 h execution limit |

## Timeline (UTC)

| Time | Event |
|---|---|
| 2026-10-03 14:00:02 | Runner START (sha `53eb2da`, fingerprint `ad68792d…`). PREFLIGHT passed every check (New York weekend: Sat 10:00 ET). |
| 14:00:08 – 14:39:23 | DOWNLOAD attempt 1, rc=0. 1,467 Alpaca requests at about 37.5/min, 0 errors, 0 retries. Main archive: 1,339 files, aggregate `4f6aa4c19184afe4…`. Diagnostic archive: 128 files, aggregate `6a9e6f121cd321bb…`. |
| 14:39:48 | Scoring stage started (worker PID 25040, venv shim 16060, runner PowerShell 20572). |
| 22:00 | Task Scheduler terminated the task at its 8 h execution limit (`LastTaskResult 0x41306 SCHED_S_TASK_TERMINATED`). **Only the runner process (20572) was killed. The shim and the worker kept running, orphaned.** No END, ABORT or CRASH line could be written. |
| 2026-10-04 00:02:23 / 00:07:35 | Two read-only `py-spy dump --locals --nonblocking` captures of the worker (owner-approved; py-spy installed in a separate scratch venv, later deleted). |
| ≈ 00:08 – 00:10:11 | Worker and shim stopped (owner GO for `Stop-Process -Id 25040,16060 -Force`). Both were confirmed gone at 00:10:11. The exact kill second is not recoverable from the logs; it falls between dump 2 (00:07:35, alive) and 00:10:11 (gone). |

**After the stop:**
- `trial_ledger.json`, `cells.csv`, `report.md` and `d0_coverage.json` are all **absent**.
- `phase_d_run.out.log` and `phase_d_run.err.log` are empty, consistent with a hard kill (no traceback).
- Commit charge dropped from 27.41 GB to 24.15 GB.

## Root cause

`research/event_response_map_v1/phase_d.py:182`, inside `events_for` (main-universe call, `phase_d.py:187`):

```python
f4rows = [r for r in f4rows if r["issuer_sym"] in set(bars_eq["symbol"])]
```

`set(bars_eq["symbol"])` was **rebuilt for every Form 4 row**, as a set over the ~10M-row bar table. That cost about 10 s per row. The list being filtered held the matched dated Form 4 rows (105,150; parse order over 158,778 development-period code-P rows).

## py-spy evidence

- **Both dumps:** MainThread is active and holds the GIL, at `events_for (phase_d.py:182)` ← `stage_run (phase_d.py:187)` ← `main (phase_d.py:407)`.
- **Already-finished locals:**
  - `k8c` = {ASSIGNED_CONSISTENT 230,247, AMBIGUOUS 6,792, NO_VALID_TICKER 17,909, DISAGREE 1,460, NO_BAR_ANY 10,752};
  - `f4c` = {MATCH 105,150, DISAGREE 2,408, AMBIGUOUS 2,118, NO_VALID_TICKER 6,587, CIK_NOT_IN_UNIVERSE 42,515};
  - `n_masked` = 370 (SIC-6770 symbol-days).
- **Loop position:** the loop variable `r` moved from accession `0001127602-19-011171` to `0001127602-19-011165`. Located by streaming the archived 2019q1 zip, read-only, these are positions **4,532 → 4,564 of 158,778**: 32 rows in 312 s, about 10 s per row, **2.9 % done**.
- **Projected remaining time:** about 17 days for this line alone. The survivorship-diagnostic pass would then repeat it. Outcomes, the 390-cell bootstrap and the diagnostic had **not started**.
- **Memory throughout:** worker private 3.3 GB, flat; machine commit at most 27.5 / 30.8 GB; page file system-managed. Not memory-bound, not thrashing (0 hard page faults per second during 60 s sampling).

## Why the earlier time estimates were wrong

The pre-run synthetic timing exercised gap events, outcomes and the bootstrap only. It **never exercised the Form 4 / 8-K attribution path at real scale**, where the per-row set rebuild lives. Lock revision 3.2 (mechanical) fixes the hot spots, and full-scale timing of every stage is required before the one allowed re-execution.
