# Task75B corporate-action preflight: specification

**This is not Task75B validation.** The preflight answers one question:

> Does the frozen `CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1` still deserve to spend its untouched validation
> holdout once its **DEVELOPMENT** data is corrected for corporate actions?

## Isolation

| Item | Value |
|---|---|
| Worktree | `C:/workspace/TalonX-task75b` |
| Branch | `research/task75b-corporate-action-preflight` |
| Base | `research/talonx-alpha-phenomenon-discovery` @ `16d2b2aac39ae20263c6ce5b79fc29c546bcf96b`, the frozen Task75A checkpoint. Not merged with and not rebased onto runtime code. |
| Live application | `feature/continuous-opportunity-engine` @ `86f7375`. **Untouched**: no process, database, Telegram or configuration change. |
| Archived RAW development bytes | read-only from `C:/workspace/TalonX-alpha-phenomenon-discovery/data/historical_1m/*` |

## Frozen identity (verified before anything else)

| Fingerprint | Value | Status |
|---|---|---|
| Full | `08930fb2bbbd1f8acbf2071be2e7bf6b2ead784a94e38837d05f4e8937eebff3` | **MATCH** |
| Contract-only | `677adccd7e653e30c96122f0149356523f3a2fb3cb82a3d4967c3a1a06aa6f06` | **MATCH** (the value recorded in `candidate_fingerprint.json`) |

## Holdout guard

`research/task75b_preflight/holdout.py` is enforced at two layers:
- **DOWNLOAD:** `check_range` runs before any request.
- **LOAD / EVALUATION:** `check_range` runs on slice bounds, and `check_frame` runs on loaded timestamps.

**States:** PREFLIGHT, TASK75B_READY, VALIDATION_RUNNING, VALIDATION_PASS, VALIDATION_FAIL, VALIDATION_INCONCLUSIVE and
REPLICATION_UNLOCKED. There is no generic READY flag.
- TASK75B_READY opens **validation only**.
- Replication opens only through VALIDATION_PASS → REPLICATION_UNLOCKED, as an explicit step.
- FAIL and INCONCLUSIVE lock replication permanently.

**Durable state and append-only audit:** `holdout_state.json`, which includes the LARGE_GAP_REVERSION_V1 researcher
exposure record. Current state: **PREFLIGHT**.

## Development windows (authoritative: Task74B `development_data_manifest.json`)

There are **four** slices, not three.

| Slice | Window | Hash |
|---|---|---|
| 2026 Q3 | 2026-05-15 → 2026-08-14 | `b8787cb099be` |
| 2025 Q1 | 2025-02-03 → 2025-03-14 | `efeccf93e369` |
| 2025 Q3 | 2025-06-02 → 2025-07-11 | `a51b01dc7844` |
| 2025 Q4 | 2025-10-27 → 2025-12-05 | `e2a34c50a60e` |

The task text listed three windows. The frozen evidence adds 2025 Q4, and the 1,000-trade anchor uses all four.

## RAW harness parity: PASS (`raw_parity.json`)

**Setup:**
- All four archived dataset hashes match the manifest.
- Data are loaded exactly as `task74b_run_discovery.py` did, including the separate SPY directory for 2026 Q3.
- The unmodified `research/task75_v1/strategy.py::evaluate()` runs per slice.

**Reproduced:**
- 1,000 trades, 35 symbols.
- Gross mean **0.6070373392207478%**, equal to the anchor within 1e-12.

**Bootstrap discrepancy, disclosed:** the recorded anchor intervals were produced by
`research.task71_lib.diagnostics.cell_summary`, which calls `bootstrap_ci_clustered(n_resamples=**2000**)` with the
default seed 670067 and `day_col=decision_day`. They were **not** produced with 10,000 resamples. That original call
reproduces the anchor **exactly**:

| Cluster | Reproduced 95% CI |
|---|---|
| Symbol | [0.06847836127667274, 1.2709696249914204] |
| Decision day | [0.034016267863865975, 1.201483098898035] |

**`decision_day` ↔ `entry_day` is bijective** on this ledger. It was verified, so the grouping is identical to
entry_day grouping.

**With the task-specified 10,000 resamples** (seed 670067, 95%) on the **same raw ledger**:

| Cluster | 95% CI |
|---|---|
| Symbol | [0.09184418920489655, 1.2820765397739222] |
| Entry day | [0.029868556767181295, 1.2049509674984649] |

This disclosed resample-count difference is resolved in the survival registration (commit 2), which requires
**both** calls to pass. The stricter of the two is binding.
