# DTU_V2 activation status: DEPLOYED, awaiting the scheduled build

> **Timestamp correction (2026-10-04 22:35Z).** This file's first version was headed "2026-10-04 22:10Z" and the matching report said "23:10 BST". Both were future-dated by about 12 minutes. Its commit `6b18f88` is dated 22:59:41 BST = **21:59:41Z**, and the system clock was verified correct at 22:06Z (GMT Standard Time, DST active). The state described below was observed at about **21:58Z (22:58 BST)**.
>
> **Superseded items.**
> - P0 has since been integrated and deployed (`ad62e9f`, 22:25Z), so the engine versions below changed; DTU_V2 is unchanged (`65f3285f8181c552`).
> - The verifier was upgraded to v2 (morning task added).
> - See `docs/research/evidence/2026-10-04_overnight_campaign.md`.

| Stage | Status | Evidence |
|---|---|---|
| Code deployed | **DONE** | Live branch `feature/continuous-opportunity-engine` at `0d1a038` (code `daa1d29`), pushed. The engine was restarted 2026-10-04 20:50:35Z: 11 components UP, 1 supervisor. |
| Configuration loaded | **DONE** | `runtime.db`: ingestion and discovery both carry config fingerprint DTU = `65f3285f8181c552` (DTU_V2, $5 / $20M / 20 sessions). Ingestion detail reports `dtu_policy=DTU_V2_LIVE_FLOOR`. Boundaries: ingestion DATA_FIX, discovery STRATEGY_MATERIAL. |
| Universe built (live) | **PENDING** | The engine builds a window's snapshot only once the window opens (`phase_at`). Window 2026-10-05 opens at 2026-10-05 00:00Z (01:00 BST). There is no supported earlier build path, and none was invented. The latest published snapshot is still `2026-10-02@2026-10-01#da27de22a3bb839a` (DTU_V1, pre-change). |
| Preview | **PREVIEW_VERIFIED** | The same code path in a scratch root: 2,090 qualifying, 1,808 removed, reconciled. An independent recomputation confirms that all 2,090 meet both floors on 20 valid sessions. |
| End-to-end verified | **PENDING** | One-off read-only Task Scheduler tasks (below). |

## Durable verification

Two one-off Windows Task Scheduler tasks are registered:
- **path:** `\TalonX\`
- **principal:** user `rites`, Interactive
- **time zone:** GMT Standard Time
- **settings:** `StartWhenAvailable`, `WakeToRun`, 2 h limit

| Task | Trigger | Polls until | Result |
|---|---|---|---|
| `UniverseVerify_2026-10-05_build` | 2026-10-05 01:15 BST = 00:15Z | 01:45Z (every 5 min) | `results/ops_restore_20261004/verify_universe_20261005_build.json` (+ `.log`) |
| `UniverseVerify_2026-10-05_premarket` | 2026-10-05 09:15 BST = 08:15Z | 09:15Z | `results/ops_restore_20261004/verify_universe_20261005_premarket.json` (+ `.log`) |

Script: `results/ops_restore_20261004/verify_universe_20261005.py` (outside tracked source). It is read-only: every SQLite handle is `mode=ro`, and it never builds, restarts or sends. Verdicts: `PASS` (exit 0), `FAIL` (1), `PENDING_TIMEOUT` (2). **No notification is sent**, so the owner reads the JSON.

**The build stage passes when all of these hold:**
- the snapshot policy is `65f3285f8181c552`, with reference session 2026-10-02 and no in-window rebuild;
- the raw sessions equal the XNYS calendar's 20 sessions, the fetch end is before 2026-10-05 00:00Z, and 0 fetches failed;
- an independent recomputation shows every qualifying member meets close ≥ 5 and ADV20 ≥ 20M on 20 valid bars, and every threshold exclusion really fails;
- the report exists, reconciles and matches the snapshot;
- discovery's admission set = the qualifying set;
- the Sentinel view shows the same snapshot version;
- the runtime registry shows DTU_V2 on both components;
- there is exactly one owner process per component.

**It also records:**
- the preview-vs-live membership differences;
- the protected (management-only) symbols, separate from the qualifying set;
- the trackers and segment registries;
- the outbox, promotion and candidate rows since the deploy (the replay and duplicate-notification check).

**The premarket stage passes when:**
- `dtu_active` has no fallback and carries the DTU_V2 fingerprint;
- discovery reports `admission=SNAPSHOT` with the same size as the qualifying set;
- there is no NEW identity outside the qualifying set.

It also records the measured PREMARKET fetch workload against 2026-10-02.

**Requires the PC to be on and the user logged on.** `WakeToRun` can wake it from sleep if wake timers are allowed. If it was off, `StartWhenAvailable` runs the task at the next logon; past the deadline, it does one check and records the verdict.
