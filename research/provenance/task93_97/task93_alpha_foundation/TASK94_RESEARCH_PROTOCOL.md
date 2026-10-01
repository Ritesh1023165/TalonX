# TASK 94 — Alpha Hypothesis Research Protocol

Frozen by Task 93 (Phase 14) at commit `4b0e5dfa2415afe1dbf423c63c9cc479264106fa`, canonical dataset
`task93_canonical_v1` (fingerprint `796893860a2733b3ffd689c81f2ce68adf96a6096cfcbbc942d7924a34e37474`),
partitions frozen in `research_partitions.json`.

Task 94 is **hypothesis-driven discovery**. It is **not** a threshold sweep, not a re-tune of the
frozen strategy, not a licence to promote anything. This protocol governs how every Task 94 experiment
is specified, run, judged, and recorded. It may only be changed by a new gatekeeper-authorised task
that records the reason.

---

## 1. Scope

**In scope:** propose economically-motivated hypotheses about intraday long-only edge on US equities;
test each once on the discovery partition; validate survivors; spend the holdout at most once per
survivor. Reuse the frozen causal replay engine and the frozen risk/execution/telemetry infrastructure
(Task 59 "keep" list).

**Out of scope (hard stops — require a new task):** changing any live decision threshold; promoting a
strategy to `talonx_quant` / `talonx_paper` / PIV; running a live/PAPER/shadow session; real capital;
adding local AI (see §9); re-partitioning; editing the frozen strategy files
(`talonx_quant/{strategy,indicators,consumer,config}.py`, `talonx_core/`, `talonx_piv/*lifecycle*`).

---

## 2. Hypothesis format

Every Task 94 experiment is a single row in the experiment ledger (`§7`) plus a one-page spec file
`results/task94_*/hyp_<ID>.md` with **exactly** these fields, all filled **before** any replay:

| Field | Requirement |
|---|---|
| **ID** | `H94-NNN` (monotonic, never reused, never deleted) |
| **Economic / market hypothesis** | One sentence: what real market behaviour creates an exploitable asymmetry. Not "indicator X predicts Y" — *why* would a rational-agent market leave this on the table (liquidity provision, forced flow, overreaction, structural constraint, session mechanics)? |
| **Causal mechanism** | The chain from cause → observable feature → forward return. Must be falsifiable. |
| **Required features** | Exact list, each computable causally from ≤ the current closed bar (+ completed HTF buffers). No feature that peeks at the entry bar's own close-to-fill move. |
| **Expected direction & horizon** | Sign of expected forward return and the holding horizon(s): choose from {5, 15, 30, 60 min, session-close, structural-stop/target}. Stated before the run. |
| **Discovery dataset** | Must be `partitions.discovery` (2025-01-24→2025-08-14, 35 symbols). Optionally a named subset — but the subset rule must be symbol-agnostic and time-agnostic (e.g. "all symbols with median regular-session ATR% > X in the *pre-discovery* warmup"), never a hand-picked list. |
| **Cost assumptions** | Report at **0 / 2 / 5 / 10 / 20 bps** round-trip (entry+exit slippage + spread, applied per `talonx_backtest.execution`). The **primary** decision figure is **5 bps**. |
| **Success criteria** | See §4 — all mandatory, all numeric, all fixed before unblinding. |
| **Rejection criteria** | See §4 — any one triggers `FAIL`. |
| **Prohibited variants** | List the parameter values / feature swaps that will NOT be tried if this fails (pre-commit to *not* fishing). |

A spec missing any field, or edited after the replay starts, invalidates the experiment (`INCONCLUSIVE`,
recorded).

---

## 3. Procedure per experiment

```
write hyp_<ID>.md  (all §2 fields)  ──►  commit it (pushed) BEFORE replay
        │
        ▼
run ONE causal replay on the discovery partition  (frozen engine, --research-telemetry)
        │
        ▼
compute the pre-declared metrics at 0/2/5/10/20 bps  ──►  compare to §4 criteria  ──►  PASS / FAIL / INCONCLUSIVE
        │ PASS only
        ▼
run ONE causal replay on the validation partition (2025-08-15→2026-02-28, 10 symbols)
        │  same criteria, no re-tuning, no criteria change
        ▼  PASS only
run ONE replay on the holdout partition (2026-03-01→08-14) — HOLDOUT IS SPENT for this ID, never re-run
        │  PASS on all three  →  candidate for a *future* implementation task (still not promotion)
        ▼
(optional) independent replication on the secondary 25-symbol holdout packages
```

- **One replay per partition per ID.** A second replay of the same ID on the same partition (for any
  reason — bug fix included) forces a **new ID**; the old ID stays in the ledger as `INCONCLUSIVE` with
  the reason.
- **No parameter adjustment, sample extension, gate change, or variant replay on a partition after its
  outcomes are unblinded.** (Same rule Task 59's `next_validation_protocol.md` set for FPRC_V1.)
- Discovery may be *looked at* freely (that is its purpose); validation and holdout may not be looked
  at until an ID reaches them.

---

## 4. Mandatory success / rejection criteria (fixed, numeric)

An experiment **PASSES a partition** only if **all** of:

| # | Criterion | Threshold |
|---|---|---|
| C1 | Trade count | ≥ 30 on the partition (else `INCONCLUSIVE — underpowered`, not FAIL) |
| C2 | Net expectancy at **5 bps** | ≥ **+0.15 R / trade** |
| C3 | Profit factor at 5 bps | ≥ **1.25** |
| C4 | Bootstrap 95% CI lower bound on 5-bps expectancy (≥ 10k resamples) | **> 0** |
| C5 | Breadth — profitable (5 bps) in | ≥ **50%** of calendar-month buckets **and** ≥ **40%** of traded symbols |
| C6 | Top-winner robustness | removing the best **3** trades keeps 5-bps total R **> 0** |
| C7 | Concentration | no single symbol > **40%** of positive R; no single month > **50%** |
| C8 | Actual-fill cost burden (mean R lost to modelled cost) | ≤ **0.20 R** |
| C9 | Zero-short invariant | 100% of trades `direction == bullish` |
| C10 | Determinism | two runs of the identical ID/partition/engine produce an identical result fingerprint |

**REJECTION (any one → `FAIL`, task stops for that ID without diagnosis or redesign):**
- Net expectancy at 5 bps < 0, **or** PF at 5 bps < 1.0.
- Bootstrap 95% CI on 5-bps expectancy includes 0 after C1 is met (i.e. adequately powered but not
  distinguishable from noise) → `FAIL` (not `INCONCLUSIVE`).
- Result consistently wrong-signed vs the pre-declared expected direction.
- C6 or C7 fails (outlier / concentration dependent).
- Any look-ahead / future-leak found in the feature set.
- Validation or holdout fails after discovery passed.

`INCONCLUSIVE` (recorded, not discarded, not grounds to retry): C1 not met; a spec-integrity violation;
an engine/data bug that invalidates the run (fix → new ID).

---

## 5. Anti-fishing rules (binding)

1. **No threshold fishing.** You may not scan a parameter grid and pick the best cell. A hypothesis
   names *one* value (or one symbol-/time-agnostic rule to derive it) up front. Sensitivity around it
   is *reported* (like Task 93 Phase 10) but never *selected* from.
2. **No repeated optimisation against the holdout.** Holdout is touched once per ID, ever.
3. **No cherry-picking symbols.** Discovery uses all 35. Any subset rule is symbol-agnostic and fixed
   before the run.
4. **No deleting losers.** Every trade the engine produces is in the population. Outlier *sensitivity*
   is a diagnostic (C6), not a filter.
5. **No selecting only profitable months / windows.** Breadth is a pass criterion (C5), computed over
   all buckets.
6. **No future leakage.** Features causal to ≤ the closed bar; fills on the next bar; HTF from completed
   buffers only. A new feature module gets its own look-ahead test (§8).
7. **No strategy promotion during discovery.** A PASS on all three partitions makes an ID a *candidate
   for a future implementation task*, nothing more. Promotion is a separate gatekeeper decision with
   its own live-qualification track (Task 90–92 style).
8. **Pre-commit prohibited variants.** Each spec lists what will *not* be tried if it fails.

---

## 6. Priority areas for hypothesis discovery (from Task 93 evidence — areas, NOT strategies)

Ranked by evidential weight that the *current* design is the binding constraint. These are **areas to
form hypotheses in**, not pre-approved changes.

| Rank | Area | Task 93 / prior evidence |
|---|---|---|
| **A1** | **Volatility-regime instrument.** The current `ATR(14)/close ≥ 0.25%` on **1-min** bars sits at ≈ the 90th percentile of *all* bars, rejects ~88–94% of bars, and (Task 38) discards genuine RSI/MACD triggers rather than dead bars. Owner (ATR-REGIME-001) explicitly said the 1-min form "must NOT be assumed to be the final intended product definition" and wants `MULTI_TIMEFRAME`. Tasks 39–41 already *designed* a 15m/60m contract (shadow-only, never adopted). **Hypothesis area:** is there a causal, multi-timeframe volatility/liquidity condition under which long continuation setups clear realistic cost — tested as a *forward-return* question, not a pass-rate question. |
| **A2** | **Entry architecture.** Task 59 concluded `REDESIGN_SIGNAL_ARCHITECTURE`: RSI/MACD/MA edge-triggers sharing one confirmation/geometry/exit model produced only +0.092 R gross / −0.324 R at 5 bps over 228 trades; MACD gross-negative; RSI winner-tail dependent and non-replicating (Tasks 55/56/58). The one specified successor `FAILED_PULLBACK_RECLAIM_CONTINUATION_V1` was never implemented; `FPRC_V1` and `ORPB_V1` (different formulations) were both REJECTED. **Hypothesis area:** a single hypothesis-specific state machine with setup-local invalidation and a thesis-failure exit — one clean idea, fully pre-registered. |
| **A3** | **Cost feasibility as a gate.** Every prior variant dies between 0 and 5 bps; the edge (where any) lives in 2–3 thin-risk-denominator names (STX/AMD/PYPL) with wide stops. **Hypothesis area:** condition entry on modelled cost-in-R feasibility (stop distance vs modelled spread+slippage) rather than a hard ATR-regime threshold — does requiring ≥ X R of headroom over cost, ex ante, change the survivorship of the population? |
| **A4** | **Exit / holding model.** Prior winners came from `END_OF_SESSION` and `SIGNAL_EXIT`, almost never `TARGET` (Task 54: 1/89 via TARGET); STOPs are fast and unpredictable (Task 19); early-exit rules are dangerous (Task 20). **Hypothesis area:** does a thesis-invalidation exit (structure break / VWAP failure / regime flip) beat the current hard bracket, measured on the *same* entry set. |
| **A5** | **Session-structure edges.** Volatility-gate passes cluster in 09:30–09:45 ET which is *also* `OPENING_BLACKOUT`-blocked (Task 38). **Hypothesis area:** is there a causal opening-range / first-N-minute structure edge that the current blackout throws away, or is the blackout correctly protecting against noise (counterfactual forward-return test on blackout-rejected candidates from Task 93 Phase 7). |

Areas **explicitly deprioritised**: broadening the universe further (Task 37/74S already show it does
not change the qualitative result); tuning `confluence_score_min` in isolation (owner confirmed
confluence is a hard gate by design — CONF-001); adding more indicator families as triggers (Task 59
"drop" list).

---

## 7. Experiment ledger

`results/task94_*/EXPERIMENT_LEDGER.md` — append-only, one row per ID, **never** edited or deleted.

| ID | Area | Hypothesis (1 line) | Spec commit | Discovery | Validation | Holdout | Status | Note |
|---|---|---|---|---|---|---|---|---|
| H94-001 | … | … | `<sha>` | PASS/FAIL/INCONC + key numbers | … | … | `OPEN`/`PASS`/`FAIL`/`INCONCLUSIVE` | why |

- **Failed experiments stay in the ledger** with their numbers and the failing criterion. They are
  evidence (they narrow the space), not waste.
- A quarterly (or per-task) roll-up counts PASS / FAIL / INCONCLUSIVE and lists what each FAIL ruled
  out.

---

## 8. Engine / code-change policy for Task 94

Same as Task 93: research-support code only, never production strategy semantics.
- A **new feature module** (e.g. a multi-timeframe volatility reader) lives outside
  `talonx_quant/strategy.py` decision logic, has its own focused tests **including an explicit
  look-ahead test**, and is wired into the replay only via a clearly-labelled research path.
- A **research-engine bug fix** must record: the bug, which prior Task 93/94 results it affects, the
  before/after trade-population delta, tests, and whether any prior conclusion is now invalid.
- The frozen strategy files stay byte-identical. If a hypothesis *requires* changing them, it is not a
  Task 94 experiment — it is a proposal for a separate implementation + re-qualification task.

---

## 9. Local AI

Not part of Task 94 by default. Propose it (`AI_USE_CASE_PROPOSAL.md`, then STOP for gatekeeper
authorisation) **only** if a concrete bottleneck appears, e.g.: too many experiment reports to
classify/triage by hand; clustering/summarising rejected-population structure where deterministic stats
are genuinely insufficient; a hypothesis-generation bottleneck that structured brainstorming + the
evidence ledger cannot address. The proposal must state the exact problem, why code/statistics is
insufficient, expected time saved, hardware/model-size cost, and risks. Do not install/train/run
anything speculatively.

---

## 10. Definition of done for Task 94

Task 94 ends (and returns to the gatekeeper) when either: (a) an ID passes discovery + validation +
holdout under §4 and is written up as a candidate for a future implementation task; or (b) a
pre-declared experiment budget is exhausted with the ledger summarising what was ruled out; or (c) a
blocker (data/engine) forces a stop. Task 94 does **not** promote, tune the frozen strategy, run a live
session, or start Task 95.
