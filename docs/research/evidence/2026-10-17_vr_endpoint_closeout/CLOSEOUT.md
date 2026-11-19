# VR_PAPER_V1 endpoint closeout: 2026-10-17

**Status: per-window EOD COMPLETE (10-01, 10-02, 10-05, 10-06). Overall study evidence: PARTIAL / INCONCLUSIVE BY
DESIGN.** This is not a strategy verdict. No study-level procedure is registered, so this document gives no pooled
metric, threshold or verdict.

- Owner authorisation: 2026-10-16, for runbook steps 3+4.
- Procedure: `docs/runbooks/2026-10-16_VR_PAPER_V1_ENDPOINT.md` §3–§4, executed 2026-10-17 00:07–00:08Z.
- Version `VR_PAPER_V1`, policy fingerprint `0d09f1427cb2c965`.
- Cost model: max(20 bps, measured entry spread) per round trip.

## §3 Stop confirmation (read-only, 00:07:17Z)

| Check | Result |
|---|---|
| UTC ≥ 2026-10-17 00:05Z | 00:07:17Z ✔ |
| VR process (`vr_live` / `tracker_vr`) | **None** ✔. Wrapper stderr empty, no traceback. The child loop exits at the first check ≥ 00:00Z; exact exit second not logged |
| Last heartbeat | 2026-10-16 20:20:33Z, window 2026-10-16, `entry_control BLOCKED` ✔ (collection end about 20:21Z) |
| Row counts | ACTIONABLE EXITED 133 / SKIPPED 729 / PAPER_ENTRY_PENDING 1; VIRTUAL_REALTIME EXITED 167 / SKIPPED 696 ✔ (unchanged) |
| OPEN | 0 ✔ |
| Trades created after the 2026-10-07 11:25:41Z boundary | 0 ✔. On 2026-10-16, 39 signals were seen and blocked |
| Tick errors in `live.log` | 0 |

**Machine state.** The machine entered Modern Standby at 2026-10-16 20:41:04Z. Kernel-Power 506 gives "Reason:
Idle", not lid (corrected 2026-10-17 06:13Z). Scheduled work kept running afterwards: this check at 00:07Z and the
06:00Z forward run. That was after the last
collection tick (20:20:33Z), so no in-window collection was lost to that sleep.

## §4a Snapshot

- Copied to `results/vr_paper/closeout_20261017/` (gitignored) with the SQLite backup API from a read-only source.
- `vr_live.db` sha256 `acf994b6a65154257c5159376e7e7fa8f3ea926d8b29e343fac214584665d070`, identical **before and
  after** the four EODs.
- Other recorded hashes (`MANIFEST.json`):

| File | sha256 |
|---|---|
| `entry_control.json` | `bd10edf6…0d82` |
| `ARM_INTERRUPTION_2026-10-07.json` | `477e20d6…58b4` |
| `UNIVERSE_SEGMENTS.json` | `bb56c1bf…c0d0` |
| `live.log` | `773cf42d…61ef` |
| `vr_paper_notifications.db` (snapshot) | `18d8d9a5…32b2` |

## §4b EOD runs

`python -m talonx_paperperf.vr_live eod <w>` ran once each for 2026-10-01, 2026-10-02, 2026-10-05 and 2026-10-06.
- All exited 0.
- The function only SELECTs from `vr_live.db` and writes `results/vr_paper/eod_<w>.json`. It makes no network or
  bar request.
- `eod_2026-09-30.json` already existed and was **not** rerun.
- `vr_replay` / `eod_vr.sh` were **not** run: replay is **NOT AVAILABLE** for 10-01…10-06, because its required
  `results/profitability/<w>.json` input was never produced.

## §4c Results: per window, per arm, never pooled

Each row is one window and one arm. Net figures are after the cost model. Returns are per-trade paper returns, and
P&L is the per-window paper portfolio figure from `eod`. **Do not sum or average across rows.**

### SEG1_DTU_V1 (windows 2026-09-30 … 2026-10-02)

| Window | Arm | n exited | Gross mean % | Net mean % | Win rate | Profit factor | Net P&L $ | Skipped | Pending |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-30 (existing EOD) | ACTIONABLE | 18 | −0.342 | −0.670 | 0.389 | 0.304 | −1,206.44 | 152 | **1 (NVCT)** |
| 2026-09-30 (existing EOD) | VIRTUAL_REALTIME | 26 | −0.315 | −0.750 | 0.385 | 0.244 | −1,112.47 | 145 | 0 |
| 2026-10-01 | ACTIONABLE | 20 | −0.126 | −0.439 | 0.300 | 0.272 | −792.59 | 180 | 0 |
| 2026-10-01 | VIRTUAL_REALTIME | 26 | −0.485 | −1.061 | 0.462 | 0.264 | −2,771.60 | 174 | 0 |
| 2026-10-02 | ACTIONABLE | 23 | +0.351 | +0.039 | 0.348 | 1.057 | +89.95 | 151 | 0 |
| 2026-10-02 | VIRTUAL_REALTIME | 31 | +0.569 | +0.192 | 0.548 | 1.503 | +720.64 | 143 | 0 |

### SEG2_DTU_V2 (observed windows 2026-10-05 … 2026-10-06)

| Window | Arm | n exited | Gross mean % | Net mean % | Win rate | Profit factor | Net P&L $ | Skipped | Pending |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-05 | ACTIONABLE | 46 | +0.031 | −0.214 | 0.348 | 0.469 | −787.33 | 142 | 0 |
| 2026-10-05 | VIRTUAL_REALTIME | 55 | +0.187 | −0.085 | 0.527 | 0.690 | −492.49 | 133 | 0 |
| 2026-10-06 | ACTIONABLE | 26 | −1.109 | −1.417 | 0.231 | 0.094 | −3,638.89 | 104 | 0 |
| 2026-10-06 | VIRTUAL_REALTIME | 29 | −0.757 | −1.087 | 0.276 | 0.153 | −3,188.36 | 101 | 0 |

**Delay effect, per window** (ACTIONABLE − VIRTUAL_REALTIME, net mean pp):

| Window | Net mean pp |
|---|---|
| 09-30 | +0.08 |
| 10-01 | +0.622 |
| 10-02 | −0.153 |
| 10-05 | −0.129 |
| 10-06 | −0.330 |

Exit reasons, skip reasons and `by_dtu` splits are in each `eod_<w>.json` (local, gitignored).

### SEG2 windows 2026-10-07 … 2026-10-16: INPUT_INTERRUPTED

- Both arms have been closed to entries since 2026-10-07 11:25:41Z, which was before that day's session.
- 0 trade rows exist for these windows. Restored review alerts were seen, blocked, and the cursor advanced.
- These are **not observations and not zero-return trades**. No EOD was produced for them.

### Pre-DTU replays 2026-09-28/29

A third population (full universe). Not part of this closeout; never pooled with SEG1/SEG2.

## Legacy NVCT row

- Row `13babda614db1b23`: `OPPORTUNITY_ENGINE:2026-09-30:NVCT:GAP_UP`, ACTIONABLE, window 2026-09-30.
- Remains **`PAPER_ENTRY_PENDING`, unresolved and never executable**. It is counted in the 2026-09-30 EOD
  `states.PAPER_ENTRY_PENDING`.
- The Telegram review alert **was delivered** (Signal outbox SENT 2026-09-30 20:03:43Z).
- The paper entry never executed. The promotion was decided at 20:03:41Z, after that window's 19:50Z flatten.
- **Row not modified.**

## Unchanged

- End date: 2026-10-16, not extended.
- VR was not restarted, and there is no scheduler entry.
- No row, lock, WAL or outbox was deleted or modified. `vr_live.db` hash is unchanged.
- No study-level summary was produced. One would need a separately approved procedure first (see
  `docs/research/evidence/2026-10-14_vr_endpoint_prep/STATE.md`).
