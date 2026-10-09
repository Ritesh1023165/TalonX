# DTU_V3_TOP600: 600-name cap on new Opportunity Engine admission (2026-10-08)

This is an owner decision. It caps membership; it is **not** evidence of profitability.

## Policy (code `7715b84`, `talonx_opportunity/universe_tiers.py`)

**`DTU_V3_TOP600`** (`CappedLiveFloorPolicy`, a subclass, so the DTU_V1 and DTU_V2 fingerprints are unchanged):
- **Floors unchanged from DTU_V2:** as-traded D-1 close ≥ $5 and ADV20 ≥ $20M, with the same data-quality rules (all
  20 sessions valid). ADV20 = mean(close × volume) over the 20 completed XNYS sessions ending at D-1, from Alpaca SIP
  1Day `adjustment=raw`.
- **Rank:** live ADV20 descending; exact ties by symbol ascending (deterministic).
- **Admissible:** ranks ≤ 600 → `ACTIVE_CORE` (`ADV20_RANK_<r>`).
- **Ranks > 600:** `AUTO_EXCLUDED`, reason `CAP_RANK_EXCLUDED_RANK_<r>_OF_<n>_CAP_600`, with its own report category,
  kept separate from the floor reasons.
- **No event tier.** There are no EVENT_ELIGIBLE rows, so the gap/8-K sweep pool is empty and no promotion can admit
  anything.
- **Fewer than 600 qualifying:** fewer are admitted. No relaxation.
- **Management unchanged.** Open setups, V2 positions, intents and execution scope, operator adds, and the window's
  Signals keep a capped-out symbol **fetched**. Discovery admits only Core names, so a protection never enables a new
  identity. Existing identities and outcome records are untouched.
- **Fingerprint and provenance.** `DTU_V3_TOP600` has its own policy fingerprint. Each snapshot records the
  cap, rank basis and event tier in `snapshot_version` / `policy_fp` and in the universe report meta. The report
  compares against DTU_V2 on the same window's recorded inputs.

## Deferred activation (no in-place rewrite, no forced build)

**Schedule.** `results/opportunity/control/dtu_policy_schedule.json` contains
`{"schedule": [{"policy": "DTU_V3_TOP600", "effective_from_window": "2026-10-09"}]}`. It was written at 20:06:18Z.

**`effective_policy(window)`** applies the latest scheduled entry whose window is on or before the current window.
**A window already published under another known policy keeps that policy.** The previous code rebuilt a window's
snapshot whenever its policy changed (`SNAPSHOT_REBUILT_POLICY_CHANGE`); that cannot happen through the schedule.
Ingestion and discovery use the same function, and Sentinel reads the published rows.

**Malformed schedule.** It is ignored, ingestion keeps its base policy, and `dtu_schedule_error` is surfaced in the
ingestion detail. Admission stays consistent.

**Boundary.**
- The next supported membership boundary is window **2026-10-09**. Ingestion builds its snapshot at window start, about
  **00:02Z on 2026-10-09 (01:02 BST)**.
- Discovery's first admission decisions under it come at the **08:00Z premarket (09:00 BST)**.

## Deployment (documented component-specific procedure; only these two components)

| Step | UTC | London | Result |
|---|---|---|---|
| Ingestion: `declare-change` #46 STRATEGY_MATERIAL, then `restart ingestion` (supervisor) | 20:06:42 | 21:06:42 BST | version 907fad4c0de0 → **dc5d119072a4**. Recorded **DATA_FIX** by `RULE:CONFIG_FINGERPRINT_CHANGED`: ingestion's forced class for config changes; the declaration was consumed. Config fingerprint `DTU=65f3285f8181c552` (window 10-08) + `DTU_SCHEDULE` |
| Discovery: `declare-change` #47 STRATEGY_MATERIAL, then `restart discovery` | 20:07:46 | 21:07:46 BST | version 063e541827a2 → **f10942d4e43c**, **STRATEGY_MATERIAL** (the admission change). `DTU_SCHEDULE` loaded |

**Verification after the restart.**
- Window 2026-10-08 still DTU_V2. The snapshot `2026-10-08@2026-10-07#65f3285f8181c552` is unchanged (built 00:02:39Z),
  with 0 rebuild transitions.
- Ingestion cycle at 20:10:12Z: active 1,550, no fallback.
- First discovery scan after the restart (20:15Z): policy `DTU_V2_LIVE_FLOOR`, admissible 2,093, admission `SNAPSHOT`.
- Single owners (shim + interpreter): ingestion 332/14916, discovery 15008/15492.
- Restarted processes reload the same code and schedule. The control file is read every tick, so the configuration
  survives supervisor respawns.

Separately, the earlier label deploy restarted the dashboard and reporting at 11:01Z (reporting declaration #45,
REPORTING_ONLY).

## Read-only preview (window 2026-10-08 inputs; `preview_2026-10-08.json`; `verify_top600.py preview`)

**Inputs.** Input sessions 2026-09-10 .. **2026-10-07** (D-1 cutoff). 2,093 qualify under both floors.

**Selection.** **600 selected.** The boundary is **PCVX $205.3M** (last in) / **XPO $205.0M** (first out). Relative to
the published DTU_V2 set: 600 retained, **1,493 removed**, 0 added.

**Distributions.** Close $5.39 / median $136.53 / max $5,931.62. ADV20 median $420M. Exchange: NYSE 375, NASDAQ 224,
BATS 1. **Sector: UNKNOWN** (no metadata stored).

**Protected subscriptions** at preview time (premarket):
- 5 open setups, all outside the top 600;
- V2 scope 39, all inside the top 600;
- 0 V2 positions or intents;
- 0 Signals.

The **estimated** total monitored was **605**. It grows by any setups open at the boundary, which stay protected until
they close.

**Workload, an ESTIMATE.** About 4 fetch batches per cycle, against 8 today (~1,500 symbols). It assumes requests scale
with symbols at about 190 per request.

## Activation verification (`verify_top600.py verify 2026-10-09`, read-only)

The verifier checks:
- the published snapshot is under the DTU_V3 fingerprint;
- Core ≤ 600;
- no EVENT_ELIGIBLE rows;
- CAP reasons appear only above rank 600;
- an independent recompute from the recorded inputs matches the snapshot;
- ingestion reports DTU_V3;
- discovery has the schedule loaded;
- singleton owners.

A missing snapshot is reported `LATE_OR_NOT_PUBLISHED`, distinct from `INVALID`. Results are appended below once
observed.

## Rollback (future boundary only; never replays or rewrites)

Append `{"policy": "DTU_V2", "effective_from_window": "<a future window>"}` to the schedule. Windows already published
under DTU_V3 keep it. No restart is needed (the schedule is read per tick), though one may be declared for the record.
Code rollback to `6458cc2` additionally requires a declared restart of ingestion and discovery. Even then, DTU_V3
windows that are already published are not rebuilt unless the window is the current one, so do code rollbacks only
between windows.

### Observed 2026-10-09 00:05:54Z: published membership `VALID`

**Snapshot.** `2026-10-09@2026-10-08#2849da5594f272db`, built **00:02:14Z** (01:02 BST) at its normal window-start time.
It was not forced and was published on time.

**Checks.** All verifier checks pass: policy fingerprint is DTU_V3, Core = 600 (≤ 600), no EVENT_ELIGIBLE,
CAP reasons only above rank 600, independent recompute matches, ingestion reports DTU_V3, discovery schedule loaded,
singleton owners.

**Boundary.** **KTOS** at rank 600 ($205.8M ADV20) is the last admitted; **XPO** at rank 601 ($205.8M) is the first
excluded.

**Universe report** (`universe_2026-10-09.json`, reconciled = true):

| Category | Count |
|---|---|
| Qualifying | 600 |
| CAP_RANK_EXCLUDED | 1,490 |
| LIQUIDITY_ONLY | 1,741 |
| PRICE_AND_LIQUIDITY | 1,543 |
| DATA_QUALITY | 193 |
| PRICE_ONLY | 81 |
| STRUCTURAL | 8,744 |

Previous (DTU_V2) pool on the same inputs: 2,090. Retained 600, removed 1,490, added 0.

**Protected at publication:** 560 names, of which **359 are outside the 600**: setups opened under DTU_V2 plus V2
scope. They stay fetched for management and are not admissible. The initial monitored total is therefore about
**960**, decaying as those setups close.

**Sentinel `/universe`** reads the same rows: Core 600, Event-eligible 0.

**Status:** *published membership active*. Consumer admission under the cap starts at discovery's 08:00Z premarket
scan (below).

### Observed 2026-10-09 08:02–08:06Z: consumers active under the cap

**Discovery.** The first PREMARKET scan with usable data (**08:02:56Z**, 09:02 BST) reported policy `DTU_V3_TOP600`,
**admissible 600**, admission `SNAPSHOT`, applied. The 08:00:55 and 08:01:56 scans were `PROVIDER_STALE` (normal SIP
lag) and made no admission decision.

**Ingestion.** The active set was cycle-written under fingerprint `2849da5594f272db`:

| Cycle | Effective active | Breakdown |
|---|---|---|
| 08:02:25Z | 959 | includes setups carried over from 10-08 |
| 08:05:26Z | **603** | 564 Core + 39 V2/operator scope (3 of the V2 names lie outside the 600); protected 0; no fallback |

**New candidates.** At the time of the check there were 0 new candidate identities for 2026-10-09, and **none outside
the admitted 600**.

**Status:** **cap active for new-opportunity admission from window 2026-10-09.**
