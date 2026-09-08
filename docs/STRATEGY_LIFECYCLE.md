# TalonX — Strategy Lifecycle & Promotion Governance

*Authoritative. Established Task 115. Every future strategy change follows this.*

## Locked rules

| | |
|---|---|
| **R1** | Any semantic change creates a **new immutable strategy version** with a new fingerprint. An already-promoted version (`INSIDER_BUY_CLUSTER_V2@1`) is **never mutated in place** — a modification becomes `@2`. |
| **R2** | No version becomes **ACTIVE live-paper** without ≥ **2-year chronological historical validation** of its **exact frozen implementation**. |
| **R3** | Validation covers: discovery/holdout separation, realistic costs, net & holdout expectancy > 0, PF > 1, sample size, concentration robustness, top-winner removal, drawdown/loss-tail, causal timing, runtime parity, practical frequency. **CI lower bound > 0 is desirable, not required** for initial paper candidacy. |
| **R4** | Research / shadow / active lanes are **isolated and non-blocking**. A failure in research/replay/shadow/dashboard never stops or corrupts ACTIVE live-paper, the Active V2 ledger, or the official alert path. |
| **R5** | Historical replay may exercise signal / Brain / paper / alert-payload construction, but external transport is **DRY-RUN ONLY** — it never sends Telegram. |
| **R6** | Promotion is **explicit**. A better historical number never auto-promotes. |
| **R7** | An ACTIVE version keeps rollback / reproducibility (frozen SHA + fingerprint + registry entry + BASELINE demotion of the incumbent). |

## Lifecycle

```
HYPOTHESIS ─▶ DISCOVERY ─▶ FREEZE VERSION ─▶ HOLDOUT ─▶ 2-YEAR EXACT RUNTIME REPLAY
   ─▶ VALIDATION VERDICT ─▶ SHADOW_ELIGIBLE ─▶ LIVE SHADOW ─▶ PROMOTION DECISION ─▶ ACTIVE
```

Registry states (`results/task115_validation_framework/strategy_registry.json`):
`RESEARCH → FROZEN → VALIDATING → {VALIDATED | FAILED} → SHADOW_ELIGIBLE → SHADOW → ACTIVE`;
plus `BASELINE` (preserved reference, e.g. `ORIGINAL_V1@1`) and `RETIRED`.
Illegal transitions (e.g. `ACTIVE → RESEARCH`) are refused.

## Immutable strategy versions

`talonx_research.versioning` — `(strategy_family, version)` + a **fingerprint** computed
only over the files that carry semantics:

- **V2**: `talonx_v2/{config,cluster_engine,liquidity,quant_bridge,brain_bridge}.py` bytes
  + frozen config scalars (`json(config) + V2_VERSION + concat(file bytes)`), first 16 hex.
  Current: **`11107198c5b81237`**. Plumbing (`service.py`, `pipeline.py`, `run.py`, dashboards)
  is **not** hashed — it may be fixed for safety/observability without a new version.
- **V1**: `talonx_quant/{strategy,indicators,config,session,consumer}.py` bytes, first 12 hex.
  Current: **`2ae6216bca70`**.

Registering a changed fingerprint under a FROZEN/VALIDATED/ACTIVE `(family, version)` raises.

## Validation gate (`talonx_research.gate`)

At the 20 bps primary cost, +10 D horizon. **Hard** (fail): net expectancy > 0, holdout
expectancy > 0, PF > 1, meaningful sample (N ≥ 60). **Findings** (pass-with-findings):
discovery > 0, no temporal-leakage proxy, issuer concentration (top issuer ≤ 60 % of positive
P&L), top-1/top-3 winner removal still > 0, ≤ half the years negative, drawdown/loss-tail
acceptable, ≥ 10 episodes/yr. **Desirable, not gating**: both dependence-aware CI lower
bounds > 0.

Verdicts: `VALIDATION_PASS` / `VALIDATION_PASS_WITH_FINDINGS` / `VALIDATION_FAIL`;
`shadow_eligible` = (not FAIL and fingerprint matches).

## Discovery / holdout (`talonx_research.holdout`)

Discovery data may be used for hypothesis development/tuning. **FREEZE** produces the
immutable fingerprint. Holdout is evaluated **only after freeze**; the runner never tunes on
holdout. For an already-frozen version validated over a fully post-freeze window (e.g. Task
116), the whole window is out-of-sample; the framework still records a chronological in-window
split and, for context, evaluates the version's original registered discovery window.

## Exact runtime replay (`talonx_research.replay_engine`)

Drives the real `talonx_v2.service.V2Service.tick()` one XNYS session at a time — the same
`detect_episodes` → staleness guard → `process_episode` → liquidity gate → `quant_bridge` →
`brain_bridge` → paper engine → `settle_due_exits` path production runs. Adapters supply only
the clock (`as_of`), the data transport (historical Form 4 + local bar CSVs) and a DRY-RUN
payload sink. **`assert_research_ledger_path` refuses the live prospective ledger** — a replay
can only write `results/…/replay_v2_lane.db`. External transport is DRY-RUN ONLY.

## Lane isolation (`talonx_research.lanes`)

| lane | alerts | ledger | writes |
|---|---|---|---|
| **ACTIVE** | real OFFICIAL alerts (paper) | `C:\workspace\TalonX\v2_lane.db` | authoritative Active V2 ledger |
| **SHADOW** | none external | its own | never the active ledger |
| **RESEARCH** | none external | its own `results/…` ledger | never active state |

Architectural, not OS resource management: ACTIVE runs in the primary worktree from the frozen
SHA; SHADOW/RESEARCH run from a separate worktree/branch + separate ledgers. The Task 114
autonomous operator classifies a SHADOW/RESEARCH failure as `DEGRADED`, never
`SESSION_BLOCKING` for ACTIVE (`Classification.OPTIONAL`).

## Explicit promotion (R6)

`StrategyRegistry.promote_to_active(version_id, decided_by, note)` — only a `VALIDATED` /
`SHADOW` / `SHADOW_ELIGIBLE` version; demotes the current ACTIVE to `BASELINE`; records the
decision. The validation manifest always carries `promotion_allowed: false`. Promotion is a
separate, authorised task — never a side effect of a validation run.

## Rollback / reproducibility (R7)

Each version's registry entry keeps its fingerprint + runtime reference + validation windows.
The ACTIVE version's live release SHA (e.g. `9bec279`, active strategy
`INSIDER_BUY_CLUSTER_V2@1`) is frozen; a demoted BASELINE stays reproducible from its own
fingerprint. To roll back: `git checkout <prior SHA>` + `registry.promote_to_active(<prior
version>)` — the prior `v2_lane.db` carry-forward is untouched by validation runs.

## Run it

```
python -m talonx_research validate --strategy INSIDER_BUY_CLUSTER_V2@1 \
    --start 2024-09-01 --end 2026-09-01 --primary-cost-bps 20 \
    --data-root C:/workspace/TalonX
python -m talonx_research registry        # list versions + states
python -m talonx_research fingerprint      # V2 semantic fingerprint
```

Evidence per run: `validation_manifest.json`, `metrics.json`, `runtime_parity.json`,
`cost_sensitivity.csv`, `concentration.json`, `monthly_results.{json,csv}`,
`trade_ledger.csv`, `alert_payloads.jsonl`, `final_report.md`, `terminal_summary.txt`.
