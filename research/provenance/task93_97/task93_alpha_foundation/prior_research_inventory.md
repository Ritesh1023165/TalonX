# TASK 93 — Phase 1: Prior Research Inventory

Forensic inventory of TalonX alpha/strategy research prior to Task 93. Sources: `results/task*/`
summary + conclusion files, `docs/research/TALONX_RESEARCH_LEDGER.md` (append-only ledger, Tasks 1–63P),
`docs/research/TALONX_OWNER_DECISIONS.md`, `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md`, and git.

**Do not blindly combine incompatible historical results.** Each entry is classified `REUSABLE` /
`PARTIALLY_REUSABLE` / `SUPERSEDED` / `INVALID_FOR_BASELINE` for Task 93's purpose (an authoritative
profitability baseline of the *current frozen* strategy `4b0e5df`).

---

## 0. The one fact that governs reuse

`git diff 848de0d..HEAD -- talonx_quant/strategy.py talonx_quant/indicators.py talonx_quant/consumer.py
talonx_quant/config.py` → **empty**. The quant strategy semantics of the current frozen build (`4b0e5df`)
are **byte-identical to Task 74S** (commit `848de0d`, 2026-08-27). Every economic result produced against
an *earlier* strategy fingerprint measures a **different strategy** and cannot be the Task 93 baseline —
at best it is context. Known strategy fingerprints in the record:

| Fingerprint | Era | Notable difference |
|---|---|---|
| `88529b8a3fa1` | Tasks 8–33 | unconditional 1.5×ATR stop; `min_atr_pct` 0.20–0.25% |
| `acd08feb59a7` | Tasks 35–48 | `MARKET_STRUCTURE_PRIMARY` stop (Task 35); trade count collapsed 26→7 |
| (post-Task-49 confluence self-credit fix; multi-timeframe *experimental* regime shadow) | Tasks 49–59 | MACD confluence self-credit corrected; family-aware confirmation |
| `2ae6216bca70` | Task 73S / 74S / **current `4b0e5df`** | the frozen build under test — **0 trades over all available history** |

---

## 1. Legacy Quant / "F1–F5" era — Tasks 3–22 (2026-08-17 → 08-20)

**Universe:** 10-symbol `task7b_alpaca_long_history` (AAPL AMD AMZN GOOGL META MSFT NVDA PYPL STX TSLA),
2025-08-15 → 2026-08-14. **Data source:** Alpaca SIP 1-min. **Strategy:** `88529b8a3fa1` era.

| Task | Hypothesis / focus | Trades | Gross | Net (cost) | Verdict | Classification |
|---|---|---|---|---|---|---|
| 3 | AAPL real-market baseline | — | — | — | baseline established | `INVALID_FOR_BASELINE` (single symbol, old engine) |
| 4 | 10-symbol trade-lifecycle discovery | — | — | — | lifecycle characterised | `INVALID_FOR_BASELINE` (mixed long/short engine) |
| 6 | Empirical baseline (short-window smoke) | — | — | — | smoke only | `INVALID_FOR_BASELINE` |
| 7B | Long-history dataset build (Alpaca) | — | — | — | dataset `5e5412a960bf` frozen | dataset **REUSABLE** (see Phase 2); results N/A |
| 8 | Frozen 0.25% ATR baseline | 93 | **−13.24 R** | — | baseline | `INVALID_FOR_BASELINE` — engine opened a real SHORT on every bearish signal (Task 24 defect); ~73.5% of trades / ~95% of gross positive R came from backtest-only shorts `talonx_paper` never opens |
| 9 | STX dominance investigation | — | — | — | STX carries the book | context only — **SUPERSEDED** by Task 26/36/14 concentration findings |
| 10 | Research telemetry | — | — | — | infra | infra reused (`--research-telemetry`) |
| 11 | ATR distribution / pass-rate (3 windows) | — | — | — | ~10% of bars clear 0.25% | **PARTIALLY_REUSABLE** as descriptive context (superseded in rigour by Task 38) |
| 12 | Post-hoc ATR threshold grid | — | — | — | grid | `INVALID_FOR_BASELINE` (post-hoc tuning on old engine) |
| 13 | ATR threshold experiment | — | — | — | — | `INVALID_FOR_BASELINE` |
| 13B | Execution-geometry fix | **181** | **+75.98 R** / PF 1.545 (0 bps) | **−21.41 R at 5 bps** | geometry fixed | `INVALID_FOR_BASELINE` (still mixed long/short) — but the *cost cliff between 0 and 5 bps* recurs everywhere after |
| 13C | Execution realism audit | — | — | — | thin after-hours liquidity flagged | context |
| 14 | **Cost sensitivity + after-hours attribution** | 181 | +75.98 R / PF 1.545 | **−21.41 R / PF 0.903 at 5 bps; −118.8 R at 10; −313.6 R at 20** | break-even reached between 0–5 bps | **PARTIALLY_REUSABLE** — methodology (cost-invariant trade population; per-scenario bps mapping) is the template Task 93 reuses; the *numbers* are `INVALID_FOR_BASELINE` (old mixed engine). Central mechanism: edge lives entirely in thin-risk-denominator names (STX 52% of book), 7/10 symbols net losers at 0 bps. |
| 15 | Risk-distance / cost-to-risk audit | — | — | — | `MIXED_CAUSES` | context |
| 16 | Entry risk preservation / cost viability | — | — | — | `TAIL_FIX_ALONE_DOES_NOT_RESTORE_EDGE` | context |
| 17 | Gross edge attribution & stability | — | — | — | **`CONCENTRATED_GROSS_EDGE`** | context — recurs in Task 26/36 |
| 18 | Volume-relationship confounding | — | — | — | `MIXED_CONFOUNDING` | context |
| 19 | Exit-path / stop-out anatomy | — | — | — | **`STOP_OUTS_BROAD_AND_NOT_PREDICTABLE`** | context — Task 21/58 echo it |
| 20 | Trade excursion / reversal anatomy | — | — | — | **`HIGH_RISK_OF_KILLING_WINNERS`** (early-exit rules dangerous) | context, still relevant to any exit redesign |
| 21 | Early-failure separability | — | — | — | `EARLY_FAILURE_WEAKLY_SEPARABLE` | `SUPERSEDED` by Task 58 |
| 22 | Freeze + OOS early-failure protocol | — | — | — | `OOS_ACCUMULATING` → later `OOS_SUSPENDED_PENDING_CANONICAL_LONG_ONLY_BASELINE` | protocol **SUPERSEDED** (built on the pre-correction engine); frozen spec hash `9c15d11c021dddbd` never resumed |

**"F1–F5"** in the roadmap shorthand maps to the signal *families* carried through Tasks 47–59: **F-RSI**
(RSI-14 curl), **F-MACD** (MACD 12/26/9 crossover), **F-MA** (SMA 10/50 crossover), plus the two
redesign candidates **FPRC_V1** (Failed-Pullback-Reclaim-Continuation) and **ORPB_V1** (Opening-Range
Pullback-Breakout). See §4–§5.

**Section verdict:** Tasks 3–22 economics are **`INVALID_FOR_BASELINE`** wholesale — Task 24 proved the
backtest engine opened real short positions the live long-only system never takes (~73.5% of trades /
~95% of gross positive R). Reusable from this era: the **dataset** (7B), the **cost-sensitivity method**
(14), and the **qualitative** findings (concentration, unpredictable stops, danger of early-exit rules).

---

## 2. The correction — Tasks 24–25C (2026-08-20)

| Task | Result | Classification |
|---|---|---|
| 24 | `MULTIPLE_MATERIAL_CORRECTNESS_ISSUES` — the backtest engine opened shorts on bearish signals; live `talonx_paper` is long-only. **This invalidates every Task 8–22 economic figure.** | the reason §1 is `INVALID_FOR_BASELINE` |
| 25A / 25A.1 | Long-only backtest parity correction + durable checkpoint | correction **REUSABLE** (in current engine) |
| 25-LIVE-CAPTURE / 25B | Live shadow evidence capture; `LIVE_FILL_GEOMETRY_VALIDATED_WITH_CAVEATS` | infra |
| 25C / 25C-reattempt | Deterministic replay vs frozen dataset → `INPUT_CAPTURE_MUTATED`, then `INCONCLUSIVE_DUE_TO_MISSING_INITIAL_STATE` | live/replay indicator-parity **still open** (noted for Task 93 as a known limitation) |

---

## 3. Corrected long-only baselines — Tasks 26, 36 (2026-08-20 → 08-22)

### Task 26 — first canonical corrected long-only baseline
- **Strategy `88529b8a3fa1`**, config `9174f5232c20`, dataset `5e5412a960bf` (10 sym, 1.9M bars, full year).
- Funnel: 1,903,044 bars → 5,021 raw candidates → **85 published** (26 bullish + 59 bearish-while-flat) → **26 trades**.
  Dominant rejections: `LOW_VOLATILITY` 1,781,848 (bar-level), `LOW_CONFLUENCE` 3,255, `OPENING_BLACKOUT` 930.
- Economics (0 bps): 26 trades, **win rate 30.8 % (95 % CI 13–48 %)**, gross **+4.289 R**, expectancy **+0.165 R (95 % CI −0.63…+0.96)**, PF 1.238, maxDD −5.76 R.
- **Cost sensitivity: 0 bps +4.289 R → 5 bps −4.636 R (PF 0.808) → 10 bps −13.56 R → 20 bps −31.41 R.** Trade population identical across scenarios (cost-invariant by construction).
- Concentration: STX+AMD+PYPL = **100 % of positive R**; STX alone 75.3 % of winner R and 57.7 % of trades; 5/10 symbols zero trades all year.
- Exit paths: STOP 18 (−1.0 R each, median 4 min), TARGET 3 (+2.72 R), END_OF_SESSION 5 (+2.83 R), SIGNAL_EXIT 0.
- **Verdict `CANONICAL_BASELINE_ESTABLISHED_BUT_EDGE_UNPROVEN`** — n=26 too small (CIs span 0); the marginal 0-bps edge is erased by 5 bps.
- **Classification: `SUPERSEDED`** (older strategy fingerprint) — but the single most informative prior baseline; its cost-sensitivity method + concentration + exit-path decomposition are the template for Task 93 Phases 6/8/9.

### Task 36 — re-baseline after `MARKET_STRUCTURE_PRIMARY` stop (Task 35)
- **Strategy `acd08feb59a7`**, same dataset/config-hash. Candidate generation unchanged (5,021).
- Population **collapsed at the R:R gate**: 85→67 published, 26→**7** bullish trades.
- Economics (0 bps): **7 trades, win rate 42.9 %, gross −0.976 R, PF 0.756 (already sub-1.0 before any cost)**, maxDD −2.95 R.
- Cost sensitivity: PF 0.756 → 0.547 → 0.402 → 0.216 across 0/5/10/20 bps.
- Only AMD (4) + STX (3) traded; 8/10 symbols zero trades.
- **Verdict `CORRECTED_CANONICAL_BASELINE_ESTABLISHED_INSUFFICIENT_SAMPLE`** — explicitly NOT cost-robust; n=7 too small to establish OR reject an edge.
- **Classification: `SUPERSEDED`** (older fingerprint) — closest in *stop geometry* to the current strategy; documents that structural stops widen the R:R gate and further starve the funnel.

---

## 4. Volatility-gate + regime work — Tasks 27, 30–46 (2026-08-21 → 08-22)

| Task | Result |
|---|---|
| 27 | `MULTIPLE_STRATEGY_DESIGN_ISSUES_REQUIRE_RESOLUTION` — the strategy's selectivity is extreme; gate interactions unresolved |
| 28 / 29 | RSI curl / confluence requirements → **`RSI_CONTRACT_LOCKED_AND_DOCUMENTED`** (RSI = candidate requiring ≥1 independent confirmation) |
| 30–33 | Operating-objective review → **owner decisions captured** (see §7) |
| 34 / 35 | `CURRENT_ATR_STOPS_SYSTEMATICALLY_MISALIGNED_WITH_STRUCTURE` → `MARKET_STRUCTURE_PRIMARY` stop implemented & validated |
| 37 | 35-symbol production-universe feasibility → **`LIKELY_TOO_SPARSE`** (~0.167 executable longs/week vs a "few/week" objective); `DOMINANT_GATE_REQUIRES_DIAGNOSTIC` |
| **38** | **`CURRENT_VOLATILITY_GATE_MISALIGNED_WITH_PRODUCT_REQUIREMENT`.** `ATR(14)/close ≥ 0.25%` on **1-min** bars sits at **≈ the 90th percentile of ALL bars**; every symbol's median ATR% is *below* 0.25% (even STX, median 0.207 %). Of 27,039 raw RSI/MACD/MA triggers only **9.15 % clear the gate** — it discards genuine triggers, not dead bars. Passes cluster in the 09:30–09:45 opening window which is *also* `OPENING_BLACKOUT`-blocked. Same symbols/periods read normal-to-high volatility at **15-min (median 0.42 %) and 60-min (0.84 %)**. Gate semantics = **`EXTREME_1MIN_VOLATILITY_FILTER`**. |
| 39–41 | Multi-timeframe volatility regime **contract designed + calibrated** (15m ATR 0.329 % / 60m 0.839 %) |
| 42–46 | Regime-shadow evaluator implemented as an **experimental / shadow-only** gate; Task 46 35-symbol check → **`INSUFFICIENT_SAMPLE`** |

**Classification:** `PARTIALLY_REUSABLE` — Task 38 is the authoritative descriptive diagnosis of the
binding constraint and directly informs Task 93 Phase 7 + Task 94 areas. The multi-timeframe regime
contract (39–41) is **designed but never adopted** into the frozen strategy (it is shadow-only) — it is
the leading Task 94 hypothesis area, not a current-strategy fact.

---

## 5. Signal-architecture A/B + redesign — Tasks 47–63P (2026-08-22 → 08-23)

| Task | n | 0 bps | 5 bps | Result |
|---|---|---|---|---|
| 47 | — | — | — | `MULTIPLE_INTERACTING_GATES_REQUIRE_FIX` (zero-bullish-publish cause) |
| 48 | — | — | — | `STATEFUL_PUBLICATION_BEHAVIOR_AMBIGUOUS` |
| 49 | — | — | — | MACD confluence self-credit bug **corrected + validated** |
| 50 | — | — | — | **`CONFLUENCE_ARCHITECTURE_REDESIGN_REQUIRED`** |
| 51 | — | — | — | Family-aware independent-confirmation contract implemented |
| 52 | — | — | — | `VALIDATION_BLOCKED` (infra) |
| 53 | 34 | +0.012 R/trade, PF 1.018 | **−0.333 R/trade** | `CANDIDATE_FREQUENCY_RECOVERED_ECONOMICS_UNCLEAR` |
| 54 | 89 (22 symbols) | +0.237 R/trade, PF 1.368, 0-bps bootstrap CI **[−0.19, +0.71]** | **−0.292 R/trade**, 2/3 windows +ve at 5 bps | **`EDGE_WEAK_AND_COST_SENSITIVE`**; removing top-3 winners flips 0-bps total R negative; RSI family +ve / MACD family −ve |
| 55 | — | RSI > MACD reproduces | — | `FAMILY_EFFECT_TENTATIVE` — RSI **not proven** superior, winner-tail dependent |
| 56 | 105 (holdout) | RSI +0.016 R / MACD −0.021 R | RSI **−0.240 R** / MACD **−0.427 R** | **`FAMILY_EFFECT_WEAKENED`**; common-support + top-winner robustness **fail** |
| 57 | 228 | +0.092 R/trade, PF 1.150 | **−0.324 R/trade, PF 0.659** | cost burden median 0.25–0.42 R; removing extreme-cost trades doesn't restore health |
| 58 | — | prior RSI +0.621 R → **+0.058 R after removing 3 winners** | — | **`PRIOR_WINNERS_CONCENTRATED`**; no stable pre-entry HTF/volatility separator reproduced |
| 59 | 228 | +0.092 R | −0.324 R | **`REDESIGN_SIGNAL_ARCHITECTURE`** — drop RSI/MACD/MA as entry triggers, same-bar confirmation, pivot R:R screening, hard ATR thresholds, opposite-family exits; keep the causal/execution/risk/telemetry infrastructure. Sole successor spec: `FAILED_PULLBACK_RECLAIM_CONTINUATION_V1`. |
| 60/61/61R | — | — | — | **`FPRC_V1_REJECTED`** — ≥1 preregistered mandatory criterion failed after unblinding |
| 62/63/63P/63R | — | — | — | **`ORPB_V1_REJECTED`** (63P) / `VALIDATION_BLOCKED` (63R — the 35-symbol Alpaca package cannot satisfy the frozen opening-range readiness gate) |

**Classification:** `PARTIALLY_REUSABLE` as the **evidentiary spine** of "no cost-robust long edge has
been demonstrated in any TalonX variant." The specific trade populations are `SUPERSEDED` (candidate
architectures, not the frozen strategy) and both redesign candidates are `REJECTED`. Task 59's
keep/change/drop list is directly reusable input to Task 94.

Datasets from this era — **REUSABLE as reserved partitions**: `task54_extended_windows` (25 sym; W1
2025-09-15→10-24, W2 2025-11-12→12-24, W3 2026-04-07→05-18), `task56_holdout` (H1 2025-12-11→01-26,
H2 2026-02-06→03-20, H3 2026-05-27→07-09), `task46_validation_windows`, `task37_universe_windows`.

---

## 6. Latest long-only evaluation — Task 74S (2026-08-27, commit `848de0d`)

- **Strategy `2ae6216bca70` = current frozen `4b0e5df`** (proven byte-identical, §0). Config `3556debe52af`,
  dataset `5e5412a960bf` (10 sym, 1,903,044 bars, full year). Primary cost 5/5/10 bps. Preregistered
  before replay; 13 fixed calendar-month buckets.
- **Result: ZERO trades, every symbol, entire ~1-year window.**
  - **93.63 %** of bars (1,781,848) rejected `LOW_VOLATILITY` before any candidate forms.
  - 5,021 raw candidates (2,488 bullish / 2,533 bearish). **72.5 %** rejected `LOW_CONFLUENCE`.
  - Only **12** bullish candidates ever cleared `confluence_score ≥ 2`; only **4** in the regular session; all 4 failed a further gate (2 `trend_component=False`, 2 `risk_reward_ratio=NaN`).
  - **0 bullish signals published → 0 trades.** 3 published signals all bearish → `NO_ACTIVE_POSITION`.
- Per-symbol: identical pattern for all 10; STX (1,994) + AMD (1,242) dominate raw candidate volume but reach 0 published bullish signals like the quiet names.
- **Verdict: `NO_ELIGIBLE_LONG_SETUPS`, universe-wide. Profitability: `INCONCLUSIVE`** (no trade population exists to assess). Data/replay correctness: **PASS**. Signal frequency: **LIKELY_TOO_SPARSE**.
- **Classification: `REUSABLE` (directly).** This is the current strategy on 1.9M of the ~4.47M canonical
  bars. Task 93's own replay is expected to reproduce it and extend it to the 35-symbol Jan–Aug-2025
  segment; its per-bucket / per-symbol funnel CSVs are directly citable.

---

## 7. Owner decisions that constrain interpretation (`docs/research/TALONX_OWNER_DECISIONS.md`, Task 33)

| ID | Owner answer | Consequence for Task 93 |
|---|---|---|
| **FREQ-001** | **`REGULAR_OPPORTUNITY`** — "a few good opportunities per week across the broad watchlist," zero-signal *days* acceptable but not long silent *periods*. | The current ~0 trades/year is **explicitly not the product intent**. Extreme selectivity is a defect to explain, not a design outcome. |
| **CONF-001** | `TRIGGER_PLUS_ONE_CONFIRMATION` — confluence is a **hard quality gate**, not just ranking. | The confluence gate is intended; its *calibration* (min score 2) is what Task 94 may examine. |
| SIG-001/002/003 | RSI, MACD, MA each = `CANDIDATE_REQUIRING_CONFIRMATION`. | family-independent confirmation is intended design. |
| **ATR-REGIME-001** | `MULTI_TIMEFRAME` — and **"`ATR(14)/price ≥ 0.25%` on 1-minute bars alone must NOT be assumed to be the final intended product definition."** | The current volatility gate is **owner-flagged as provisional/likely-wrong**. Task 38 confirmed it is misaligned. Leading Task 94 area. |
| ATR-TRIGGER-001 | Accept current `ATR(14)` 1-min for *trigger-movement*. | trigger ATR is fine; regime ATR is the issue. |
| **COST-001** | Realistic spread + slippage assumed; **"do NOT reverse-engineer [a deployability bps threshold] from Task 26's cost-sensitivity result."** | Task 93 reports 0/2/5/10/20 bps as *sensitivity*, names no pass/fail bps line. |

---

## 8. Consolidated reuse table

| Prior artifact | Use for Task 93 | Class |
|---|---|---|
| `task7b_alpaca_long_history` (10 sym, 2025-08-15→2026-08-14), dataset hash `5e5412a960bf` | Segment B of the canonical dataset | **REUSABLE** |
| `task63_orpb_v1_validation` + `task61r_fprc_v1_validation` (35 sym, 2025-01-24→2025-08-14, contiguous, 0 defects) | Segment A of the canonical dataset (the broad universe) | **REUSABLE** |
| `task54_extended_windows`, `task56_holdout`, `task46_validation_windows`, `task37_universe_windows` (25 sym, scattered 2025-09→2026-07) | additional reserved holdout material for Task 94 (different symbols) | **REUSABLE** |
| Task 74S funnel / per-symbol / per-bucket CSVs (current strategy, 0 trades) | Phase 5/7 baseline for Segment B; cite directly | **REUSABLE** |
| Task 26 cost-sensitivity + concentration + exit-path method | Phase 6/8/9 method template | **PARTIALLY_REUSABLE** (method only; numbers old-engine) |
| Task 14 cost-invariant-population method + per-scenario bps mapping | Phase 6 (incl. deriving 2 bps) | **PARTIALLY_REUSABLE** |
| Task 38 volatility-gate diagnostic | Phase 7 + Task 94 areas | **PARTIALLY_REUSABLE** (descriptive; earlier strategy fingerprint but gate unchanged) |
| Task 59 keep/change/drop + `next_validation_protocol.md` | Task 94 protocol input | **PARTIALLY_REUSABLE** |
| Tasks 8–22 economic figures (93-trade −13.24 R, 181-trade +75.98 R, grids) | — | **INVALID_FOR_BASELINE** (mixed long/short engine, Task 24) |
| Task 26/36 trade populations (26, 7 trades) | context on how the funnel starves as stops tighten | **SUPERSEDED** (older strategy fingerprints) |
| FPRC_V1 / ORPB_V1 candidate economics | — | **SUPERSEDED / REJECTED** (not the frozen strategy) |
| Task 22 frozen OOS early-failure protocol (`9c15d11c021dddbd`) | — | **SUPERSEDED** (pre-correction engine; never resumed) |

## 9. Bottom line entering Phase 2–5

Across **every** economic evaluation of a TalonX long-only strategy variant to date (Tasks 14, 26, 36,
53, 54, 56, 57, 59) the finding is the same: **no cost-robust long edge has been demonstrated** — gross
results are near-flat-to-slightly-positive at 0 bps, **negative by 5 bps**, driven by 2–3 thin-risk
names, and dependent on a handful of winners. The **current frozen strategy** (`4b0e5df` = Task 74S
semantics) is more selective still: **0 executable long setups over 1.9M bars / 10 symbols / 1 year**,
bottlenecked at `LOW_VOLATILITY` (bar level, ~94 %) then `LOW_CONFLUENCE` (candidate level, ~72 %). Task
93's replay is expected to confirm and broaden this. No prior result supports `CURRENT_STRATEGY_EDGE_
SUPPORTED`; none demonstrates a *negative* edge for the current strategy either (it does not trade).
