# Handoff — Task 67A/67B Complete

Read this before doing anything else; no prior chat history needed.

## State

- **Research branch**: `research/talonx-alpha-phenomenon-discovery` (isolated worktree at `c:\workspace\TalonX-alpha-phenomenon-discovery`), pushed to `origin`.
- **Canonical runtime branch**: `research/talonx-strategy-validation` at `c:\workspace\TalonX`, HEAD `d9749f3813d2c5495109b470df616faceb127ffc` — **untouched throughout Task 67A/67B**, tree clean, zero live runners/schedulers.
- **Deployment**: no live/paper session was started by this work; nothing here executes trades.
- **Alpha status**: **UNPROVEN.** This work is DEVELOPMENT-data-only exploratory screening, not validation, not a backtest, not a strategy freeze.

## What happened (2026-08-24 night → 2026-08-25 morning)

**Task 67A** (overnight, interrupted partway by an external session rate-limit reset): built the data-readiness foundation — a DEVELOPMENT/VALIDATION/REPLICATION split contract (`data_split_contract.json`/`.md`), a full data/exposure audit, SPY + 7 sector-ETF benchmarks, and a shared statistics toolkit (`research/task67a_lib/research_stats.py`). The interruption meant the actual 6-family screening never started that night — only scaffolding (`screening_framework.py`) existed, and it had a real bug (10/23 tests failing).

**Task 67B** (same morning, continuing from that checkpoint) did the actual work:
1. **Fixed `screening_framework.py`** — root cause was a tz-aware-datetime object-dtype bug (a helper meant to fix this, `_naive_utc_ns`, existed but was never actually called). Also fixed two latent secondary bugs (a same-day warmup detection gap in `causal_atr_proxy`, a `pd.qcut` label-count mismatch on constant test data), plus the *same* class of bug independently in `research_stats.cross_family_overlap` (caught during cross-family synthesis, since no family had called that function before). All fixed, all pinned with explicit regression tests. **126 tests pass** across the full `tests/test_task67a_*.py` suite.
2. **Screened all 6 preregistered families** on DEVELOPMENT data (35 symbols, 2026-05-15→2026-08-14, 62-63 trading days depending on exact counting convention — see `data_inventory.json`), 3 broad definitions × 4 horizons (15/30/60/120m) each, with de-duplication, matched controls, clustered bootstrap CIs, concentration checks, effect-surface stability checks, and the shared `PHENOMENON_PRESENT`/`WEAK_SIGNAL`/`PHENOMENON_NOT_OBSERVED`/`INSUFFICIENT_DATA` taxonomy throughout.
3. **Cross-family synthesis**: event-overlap matrix, gross-effect comparison, and a fixed-in-advance composite ranking.

## The one finding that matters

**Family 6 (opening information → later-session)** is the only family where all 3 of its definitions independently reach `PHENOMENON_PRESENT`. But the direction is the **opposite of the original hypothesis**: strong opening-30-minute moves (however measured — absolute magnitude, SPY-relative strength, or relative volume) predict a coherent **NEGATIVE (fade/mean-reversion)** excess return into the rest of the session, not continuation. This holds across 15/30/60/120m horizons, CI excludes zero at 15m/60m/120m, economics are `POTENTIALLY_TRADEABLE`, breadth is full (35/35 symbols, 63/63 days), concentration is low, and the effect surface is stable. **A Stage 2 spec built from this must freeze a fade rule, not a continuation rule** — see `task67b_summary.json`'s `candidates_nominated[0].critical_reframing_for_stage_2` for the exact reasoning, and `.what_stage_2_would_need_to_freeze` for what's still undecided (which of the 3 signal variants, exact holding horizon, a realistic execution cost model, and the validation protocol).

All other 5 families: `family_03_range_expansion` had one attractive-looking but fragile definition (small n=76, unstable effect surface — explicitly NOT nominated, flagged as a watch item only); Families 1/2/4 showed real but economically-too-thin structure (`WEAK_SIGNAL`, mostly `ECONOMICALLY_TOO_SMALL`); Family 5 was a clean negative (`PHENOMENON_NOT_OBSERVED` on all 3 definitions — compression alone, without an active breakout, does not predict anything on this data).

## Stage 1 Decision

**PHENOMENON_READY_FOR_STAGE_2** — Family 6 only (reframed as a reversal hypothesis). Full reasoning and what Stage 2 needs to freeze: `task67b_summary.json`/`.md`. Ranking/overlap detail: `cross_family_summary.json`/`.md`, `family_comparison.csv`, `event_overlap_matrix.csv`, `phenomenon_ranking.json`.

## Data discipline (do not violate this)

- **DEVELOPMENT** (2026-05-15→2026-08-14, materialized, iterated on freely tonight): `data/historical_1m/task67a_development/`.
- **VALIDATION** (2026-08-25→2026-09-22) and **REPLICATION** (2026-09-23→2026-10-21): reserved by calendar date ONLY, **not materialized** (the data does not exist on disk — it's genuinely in the future). Enforced by `research/task67a_lib/data_guard.py`'s `DataSplitGuard`/`BlockedDataRoleAccessError`/`UnmaterializedRoleError`. **Do not attempt to download or use either until the relevant calendar window has actually elapsed** — VALIDATION not before 2026-09-23, REPLICATION not before VALIDATION has been run and passed. See `data_split_contract.md`'s `materialization_instructions` for the exact procedure when that time comes.
- If Stage 2 needs to iterate on a frozen spec after a first look at VALIDATION, that iteration invalidates that VALIDATION pass — REPLICATION becomes the next honest check, not a second look at the same VALIDATION data.

## Protected files — verified unchanged throughout

`talonx_quant/{strategy,indicators,consumer,config,fprc_v1,fprc_v1_shadow,orpb_v1,orpb_v1_shadow}.py`, `talonx_brain/`, `talonx_core/`, `talonx_dispatch/`, `talonx_paper/` — sha256 fingerprints re-verified fresh against `protected_files_fingerprint_manifest.json` at the end of Task 67B; all 8 individually-hashed files identical. `orpb_v1.py` was never opened by any family script (Family 3 and Family 6 were both explicitly required to be independent of ORPB logic).

## Exact next recommended task

**Stage 2**: design (not yet code) a frozen causal trade-rule spec for the Family 6 fade hypothesis — pick one signal variant (or a documented, non-cherry-picked combination), a decision timestamp (14:00 UTC / 30m post-open, as used throughout Stage 1), a holding-horizon/exit policy, and a realistic execution cost model — then validate it against the VALIDATION window once 2026-09-23 has passed and that data can be honestly materialized. Do not start Stage 2 code or touch VALIDATION/REPLICATION data before that.
