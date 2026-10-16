# VR_PAPER_V1 endpoint runbook (registered end date 2026-10-16)

**Prepared 2026-10-14 ~12:10Z (13:10 BST).** This is preparation only: nothing in it has been executed. Execution is a
separate endpoint task. Its outcome-reading steps (§4) require explicit owner authorisation at that time.

## 1. The endpoint, as enforced by code

| Item | Source |
|---|---|
| Registered end date | **2026-10-16, inclusive**. Sources: wrapper `results/ops_restore_20261004/tracker_vr.sh` (`--until 2026-10-16`); `results/vr_paper/UNIVERSE_SEGMENTS.json` (`end_date 2026-10-16 (unchanged)`); `ARM_INTERRUPTION_2026-10-07.json`; `docs/research/evidence/2026-10-04_live_universe_floor/README.md`. |
| Child stop condition | `talonx_paperperf/vr_live.py main()`: `while datetime.now(UTC).date() <= until` (the default `until` is also 2026-10-16), 60 s sleep. The **UTC calendar date** governs. |
| Collection on 2026-10-16 | Ticks only inside the exchange-calendar window for that UTC date: from premarket start **08:00Z** (04:00 ET, 09:00 BST) to close + 16 min SIP delay + 5 min, **20:21Z** (16:21 ET, 21:21 BST). 2026-10-16 is a normal Friday, close 20:00Z (16:00 ET). Half days are handled by `trading_window` (tested). |
| Position management on 2026-10-16 | Intraday only: `SESSION_CLOSE` flatten at **15:50 ET = 19:50Z (20:50 BST)**. Stop and target are checked on 1-minute bars. A position is managed only by ticks of its own window. |
| Child exit | At the first loop check at or after **2026-10-17 00:00Z** (20:00 ET 10-16; 01:00 BST 10-17), within about 60 s. A tick in progress is bounded by 30 s HTTP and SQLite timeouts. A slow tick crossing midnight ends the loop (tested). |
| Relaunch | The wrapper runs the command **once** (no loop). There is no Task Scheduler entry and no supervisor for VR. A relaunch after the endpoint ticks **nothing** and exits immediately (tested). Only a launch with a later `--until` could collect again, so never pass one. |
| Docs vs code | Consistent. **No overrun defect found. No runtime correction is needed.** |

## 2. State at preparation (operational metadata only; no returns read)

- **Tracker:** one chain, `tracker_vr.sh` 18004 → 19580 → `vr_live run --until 2026-10-16` 18688/21460, started
  2026-10-07 22:41Z.
- **Heartbeat:** 2026-10-14 12:04:27Z, window 2026-10-14, `entry_control BLOCKED`, boundary 2026-10-07 11:25:41Z,
  open 0 / 0.
- **Entries:** **0** trade rows created and **0** entries at or after the boundary. **0 OPEN.**
  - Cursors advanced for 10-08 … 10-13: restored review alerts were seen and blocked.
- **Row states** (counts only):

  | Arm | EXITED | SKIPPED | PAPER_ENTRY_PENDING |
  |---|---|---|---|
  | ACTIONABLE | 133 | 729 | 1 |
  | VIRTUAL_REALTIME | 167 | 696 | 0 |

- **Legacy pending row:** `trade_id 13babda614db1b23`, `OPPORTUNITY_ENGINE:2026-09-30:NVCT:GAP_UP`, ACTIONABLE, window
  2026-09-30, signal 19:38Z, `signal_wall_time` null, created and updated 2026-09-30 20:03:48Z.
  - It is **not executable**: the live loop only processes the current UTC-date window (tested).

## 3. At or after 2026-10-17 00:05Z: confirm the stop (read-only)

```powershell
Set-Location -LiteralPath C:\workspace\TalonX
(Get-Date).ToUniversalTime()                                   # must be >= 2026-10-17 00:05Z
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vr_live|tracker_vr' } |
  Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine   # expect: none
.venv\Scripts\python.exe -c "import sqlite3,json; c=sqlite3.connect('file:results/vr_paper/vr_live.db?mode=ro',uri=True); h=c.execute('select at_utc, detail_json from heartbeat').fetchone(); d=json.loads(h[1]); print(h[0], {k:d.get(k) for k in ('window','entry_control','open_vr','open_act')}); print(c.execute('select paper_mode,state,count(*) from trades group by 1,2').fetchall()); print('OPEN', c.execute(\"select count(*) from trades where state='OPEN'\").fetchone()[0])"
```

**Expected:**
- No VR process remains.
- The last heartbeat is on 2026-10-16, at or before about 20:21Z.
- `OPEN 0`.
- Row counts are unchanged from §2 (entries stay blocked).

**If a VR process is still alive after 00:05Z** (not expected; a proposal only, never executed by this preparation):
1. Re-verify its identity: the command line exactly `-m talonx_paperperf.vr_live run --until 2026-10-16` and ancestry
   `tracker_vr.sh`.
2. Confirm the heartbeat is not advancing a tick.
3. `Stop-Process -Id <python child> ; Stop-Process -Id <venv launcher> ; Stop-Process -Id <bash wrappers>`.
4. Record the PIDs and times. **Never delete `vr_live.db`, its WAL/SHM, or any lock or outbox.**

**Prevent relaunch.**
- Do not run `tracker_vr.sh` again, and never pass a later `--until`.
- There is no scheduler entry to disable. Running it again would only exit immediately.

## 4. Closeout (separate endpoint task; owner authorisation required before any outcome is read)

**4a. Read-only snapshot and hashes** (after §3 passes):

```powershell
.venv\Scripts\python.exe -c "import sqlite3,hashlib,pathlib,json; d=pathlib.Path('results/vr_paper/closeout_20261017'); d.mkdir(exist_ok=True); m={}
for n in ('vr_live.db','vr_paper_notifications.db'):
    s=sqlite3.connect(f'file:results/vr_paper/{n}?mode=ro',uri=True); t=sqlite3.connect(d/n); s.backup(t); t.close(); s.close()
for p in list(d.glob('*.db'))+[pathlib.Path('results/vr_paper/'+x) for x in ('entry_control.json','ARM_INTERRUPTION_2026-10-07.json','UNIVERSE_SEGMENTS.json','live.log')]:
    m[str(p).replace(chr(92),'/')]=hashlib.sha256(p.read_bytes()).hexdigest()
(d/'MANIFEST.json').write_text(json.dumps(m,indent=1)); print(json.dumps(m,indent=1))"
```

**4b. Run the registered evaluation once**, only the missing per-window `vr_live eod`, and only for **observed**
windows:

| Segment | Window | Status |
|---|---|---|
| SEG1_DTU_V1 | 2026-09-30 | EOD **exists** (`eod_2026-09-30.json`, `replay_2026-09-30.json`); do not rerun |
| SEG1_DTU_V1 | 2026-10-01, 2026-10-02 | EOD **missing** |
| SEG2_DTU_V2 | 2026-10-05, 2026-10-06 | EOD **missing** (observed before the interruption) |
| SEG2_DTU_V2 | 2026-10-07 … 2026-10-16 | **INPUT_INTERRUPTED** (both arms closed at 2026-10-07 11:25:41Z). **No EOD; not observations; never zero-return trades.** |

```powershell
foreach ($w in '2026-10-01','2026-10-02','2026-10-05','2026-10-06') { .venv\Scripts\python.exe -m talonx_paperperf.vr_live eod $w }
```

- `eod` reads `vr_live.db` (SELECT only) and writes `results/vr_paper/eod_<w>.json`.
- It is per window and per arm (`VIRTUAL_REALTIME`, `ACTIONABLE`, `by_dtu`, the per-window delay effect), and it
  labels `oe_universe_segment`.
- Re-hash `vr_live.db` afterwards and expect it unchanged.
- **Do not run `vr_replay` / the replay half of `eod_vr.sh`.** Its required input `results/profitability/<w>.json` (the
  per-session `signal_forensics` / `eod_profit.sh` forensic of a different study track) was never produced after
  2026-09-30, and replay would fetch new bars. Producing it is a separate authorisation. Report replay as **NOT
  AVAILABLE** for those windows.

**4c. Reporting under the existing rules:**
- Keep **SEG1** (09-30 … 10-02), **SEG2** (10-05 … 10-06 observed) and the pre-DTU replays (09-28/29) **separate, never
  pooled** (`UNIVERSE_SEGMENTS.json` rule).
- Keep **ACTIONABLE vs VIRTUAL_REALTIME** separate.
- Report 10-07 … 10-16 as INPUT_INTERRUPTED coverage.
- **The legacy NVCT pending row:** report it as `PAPER_ENTRY_PENDING`, unresolved and never executable (its window
  closed; the paper entry was never executed before flatten). Telegram delivery and paper entry are separate: the
  review alert itself **was delivered** (Signal outbox `SENT` 2026-09-30 20:03:43Z); only the VR paper entry never
  happened (promotion decided 20:03:41Z, after the 19:50Z flatten). **Do not delete, rewrite or "resolve" it.** `eod` already counts it under
  `states.PAPER_ENTRY_PENDING` for 2026-09-30.
- **No study-level procedure is registered.** The registration provides per-window EOD only, with no pooled metric,
  acceptance threshold or study-level verdict. Do not invent one. If a study-level summary is wanted, it needs a
  separately approved procedure first (draft gap: `docs/research/evidence/2026-10-14_vr_endpoint_prep/STATE.md`).
- Status vocabulary: per-window EOD **COMPLETE** for the evaluated windows. Overall study evidence:
  **PARTIAL / INCONCLUSIVE BY DESIGN**, because of the input interruption and the missing replay inputs, not a
  strategy verdict.

## 5. Never

- Resume entries or reconnect either arm.
- Extend the end date.
- Backfill observations, fabricate send times or substitute promotion timestamps.
- Rewrite the pending row.
- Run evaluations before 2026-10-17 00:05Z or without owner authorisation.
- Create a scheduled evaluator or an unattended stop task.
