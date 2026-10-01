# TASK 93 — ALPHA RESEARCH FOUNDATION & FROZEN BASELINE — FINAL REPORT

## 1. Executive verdict

# `CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN`

The current frozen TalonX long-only strategy (`4b0e5dfa2415afe1dbf423c63c9cc479264106fa`,
`strategy_version 2ae6216bca70`) produces **one trade across all locally-available history** —
2,565,682 bars / 35 symbols / 6.7 months (Segment A) plus 1,903,044 bars / 10 symbols / 12 months
(Segment B, Task 74S). There is **no trade population to evaluate**. The one trade (PYPL 2025-04-30,
+5.99 R at 0 bps) is statistically indistinguishable from a single lucky random entry (≈ +1.2 σ above
the random-entry mean; beaten by ~1 in 9 random draws).

- **Not `SUPPORTED`** — no reasonable sample, no cost resilience test possible, no breadth across
  time/symbols/regimes, uncertainty is total.
- **Not `REJECTED`** — the *current* strategy shows no negative edge; it simply does not trade. The
  well-evidenced negative cost-sensitivity findings (edge vanishes by 5 bps) belong to **superseded,
  more-permissive** strategy versions (Tasks 14/26/36/54/57), not this one.
- **Not `TASK93_BLOCKED_DATA_OR_ENGINE`** — the data is clean (0 structural defects / 4.47M bars) and
  the engine ran deterministically. The constraint is the strategy's own selectivity, not the
  research infrastructure.

The frozen strategy's selectivity is **~3 orders of magnitude below** the owner's stated
`REGULAR_OPPORTUNITY` intent ("a few good opportunities per week across the broad watchlist").

## 2. Dataset

`task93_canonical_v1` (fingerprint `sha256 796893860a2733b3ffd689c81f2ce68adf96a6096cfcbbc942d7924a34e37474`).

| | |
|---|---|
| Symbols | **35** — `talonx_piv.DEFAULT_UNIVERSE` / FPRC-ORPB validation set (not profitability-selected) |
| Period | **2025-01-24 → 2026-08-14** (~18.7 months). No pre-2025 data exists anywhere locally. |
| Bars | **4,468,726** (Segment A broad: 2,565,682 · Segment B deep-10: 1,903,044) |
| Source | Alpaca 1-minute OHLCV, UNADJUSTED, extended hours included |
| Quality | 0 duplicates / 0 out-of-order / 0 NaN·Inf / 0 invalid OHLC / 0 negative volume across all 80 source files. ~218k benign intra-minute gaps (empty minutes omitted, not zero-filled). **1 MINOR** bad pre-market print (AMD 2025-10-06 12:07 UTC) — documented, data left unmodified. No BLOCKING issue. |
| Limitation | one macro regime in the broad segment (2025 H1); no bear/crisis regime anywhere; individual-security (mild survivorship). |

Partitions frozen (`research_partitions.json`): discovery 2025-01-24→08-14 (35 sym), validation
2025-08-15→2026-02-28 (10 sym), holdout 2026-03-01→08-14 (10 sym, untouched).

## 3. Current strategy (Segment A replay, 0 bps, deterministic)

| Stage | Count |
|---|---:|
| Post-warmup bar evaluations | 2,561,517 |
| Pass volatility gate (`ATR%≥0.25`, 1-min) | 184,842 (7.2%) |
| Raw candidates | 7,647 (bullish 3,900 / bearish 3,747; MACD crosses 94%) |
| Clear confluence `≥ 2` | **35** (0.46%) |
| …bullish + regular session + HTF-trend + R:R≥1.5 | **1** |
| **Signals published / trades** | **1 / 1** |

| Metric | Value |
|---|---|
| Trades | 1 · Wins/Losses | 1 / 0 |
| Win rate | 100% (CI uninformative at n=1) |
| Expectancy | +5.99 R · Total R | +5.99 · Median R | +5.99 |
| Profit factor | ∞ (0 losses) · Max drawdown | 0 R |
| Avg holding | 349 min · Exit | `END_OF_SESSION` · Turnover | 1 round-trip / 6.7 mo / 35 sym (~0.15 trades/month) |
| The trade | PYPL, 2025-04-30, `rsi_oversold_volume_surge`, entry $64.00, stop $63.738 (ATR_FALLBACK), target $67.70, RR 15.4, confluence 2, MFE +5.99 R, MAE −0.50 R |

**Segment B (Task 74S, identical strategy):** 0 trades / 1,903,044 bars — 93.6% bars `LOW_VOLATILITY`,
72.5% candidates `LOW_CONFLUENCE`, 0 bullish signals published.

## 4. Costs (`cost_sensitivity.csv`)

n = 1 — this is arithmetic on one trade, **not a strategy conclusion**. Trade population is
cost-invariant by construction (gate/geometry use raw prices).

| bps | Net total R | Cost burden (R) |
|---:|---:|---:|
| 0 | 5.9907 | 0.000 |
| 2 | 5.8918 | 0.099 |
| 5 | 5.7435 | 0.247 |
| 10 | 5.4963 | 0.494 |
| 20 | 5.0019 | 0.989 |

The one trade stays a large winner at 20 bps only because it is a +6 R outlier with a huge cushion.
**Nothing about the strategy's cost robustness can be inferred from one trade.** For context, every
prior (superseded) strategy version with a real trade population went net-negative between 0 and 5 bps
(Task 14: +76 R → −21 R; Task 26: +4.3 R → −4.6 R; Task 54: +0.24 → −0.29 R/trade; Task 57: PF 1.15 →
0.66).

## 5. Funnel (`funnel_decomposition.csv`, `funnel_analysis.md`)

Two compounding walls:
1. **Volatility gate** removes **92.8%** of bars before any trigger is evaluated. The 0.25% 1-min-ATR%
   floor sits between the **90th and 95th percentile of every bar**; median bar ATR% is 0.087%
   (Task 38 confirmed). **Counterfactual:** the rejected bars have **≈ zero forward long edge**
   (flat, ~50% hit at +5/15/30/60 min, ~−1 bps EOD) — indistinguishable from random. So the gate is
   removing **noise, not profit** — but it is also removing *frequency* and genuine triggers, and is
   owner-flagged (`ATR-REGIME-001`) as not the final intended instrument.
2. **Confluence gate** (`score ≥ 2`) passes only **35 of 7,647** candidates. **Counterfactual:** the 15
   regular-session bullish survivors had **strong near-term continuation** (+114 bps at 15 min, 80%
   hit) vs the LOW_CONFLUENCE-rejected regular bullish population (+9 bps, 52%). The confluence gate
   **is genuinely selective** — but the edge is short-lived (turns −20 bps by EOD), n = 15, mostly one
   month.

Most important rejection populations: `LOW_VOLATILITY` (2,376,675 bars) and `LOW_CONFLUENCE` (5,290
candidates, first-failure). `OPENING_BLACKOUT` (1,418) and `SESSION_CLOSED`/`CLOSING_BLACKOUT` (889)
account for most of the rest.

## 6. Concentration (`concentration_analysis.md`)

Trade-level: **degenerate (n=1)** — 100% PYPL / April 2025 / RSI family / high-volatility regime /
EOD exit. Candidate-level: **49.9% of all candidates over 6.7 months came from April 2025 alone** (the
tariff-shock volatility spike); top-5 symbols = 35.7% of candidates (TSLA/INTC/NVDA/AVGO/LRCX). What
little the strategy does is a **volatility-regime-conditional, single-stressed-month** phenomenon.

## 7. Robustness (`outlier_robustness.csv`, `parameter_stability.md`)

- **Outlier:** removing the single trade → 0 trades, everything to zero. Degenerate; a restatement of
  n=1.
- **Parameter sensitivity (no tuning, no selection):** volatility-floor *pass-rate* responds smoothly
  (≈ doubles per 0.05% loosening — not knife-edge), but loosening it only adds noise-grade candidates;
  the confluence floor is at a real breakpoint (nothing scores > 2 in Segment A; score 1 dilutes
  toward noise; score 3 → 0 candidates). The result's **sparsity is structurally stable**; its
  **+5.99 R P&L is maximally fragile** (= n=1).

## 8. Statistical confidence (`statistical_confidence.md`)

**n = 1 → no CI, bootstrap, Sharpe, or PF uncertainty is meaningful** (engine emits `SMALL SAMPLE`
and returns `expectancy_ci: null`). The one trade is ≈ +1.2 σ above the random-eligible-long mean
(+245 bps vs mean +4 bps, std 203 bps; n≈16k) — inside single-draw noise. Prior larger populations
(Tasks 26/36/54/56, superseded strategies) all had 0-bps expectancy CIs spanning zero.

## 9. Prior-research reconciliation (`prior_research_inventory.md`)

| Prior conclusion | Status after Task 93 |
|---|---|
| Task 74S: current strategy → `NO_ELIGIBLE_LONG_SETUPS` / `INCONCLUSIVE` (10 sym / 1 yr, 0 trades) | **Confirmed & broadened** — 35 sym / 6.7 mo adds exactly 1 trade. |
| Task 37: 35-symbol universe `LIKELY_TOO_SPARSE` | **Confirmed** — ~1 trade / 6.7 mo / 35 sym. |
| Task 38: 1-min volatility gate = `EXTREME_1MIN_VOLATILITY_FILTER`, misaligned with product | **Confirmed** (0.25% ≈ p90–p95) **and extended** — Phase 7 shows the rejected bars also have ~zero forward edge (gate removes noise, but destroys frequency). |
| Tasks 14/26/36/54/57: no cost-robust edge, dies by 5 bps, STX/AMD/PYPL-concentrated, outlier-dependent | **Still valid — for those (superseded) strategy versions.** Not re-testable on the current strategy (no trades). |
| Task 59: `REDESIGN_SIGNAL_ARCHITECTURE`; FPRC_V1 & ORPB_V1 both `REJECTED` | **Unchanged.** Task 93 adds that the confluence *concept* shows real short-horizon selectivity (Phase 7) — an input to Task 94, not a reversal. |
| Tasks 3–22 economics (mixed long/short engine) | **`INVALID_FOR_BASELINE`** — unchanged. |

**Superseded by this report:** any characterisation of the *current frozen strategy's* profitability
from the Task 26/36 trade populations. Task 93 is now the authoritative baseline: **1 trade,
un-assessable edge.**

## 10. Task 94 recommendation — highest-priority AREAS (not strategies)

Full protocol: `TASK94_RESEARCH_PROTOCOL.md`. Ranked areas:

1. **A1 — Volatility-regime instrument.** The 1-min ATR% floor is the frequency bottleneck and (Phase
   7) removes noise not profit; owner wants `MULTI_TIMEFRAME`; Tasks 39–41 already designed a
   15m/60m contract (shadow-only, never adopted). Form *forward-return* hypotheses about a
   multi-timeframe volatility/liquidity condition for cost-clearing long continuation.
2. **A2 — Entry architecture.** Task 59's `REDESIGN` stands; the confluence concept shows real
   near-term selectivity (Phase 7) — build one hypothesis-specific state machine, fully pre-registered.
3. **A3 — Cost feasibility as an ex-ante gate** (stop distance vs modelled spread+slippage) instead of
   a hard ATR-regime threshold.
4. **A4 — Thesis-invalidation exit** vs the current hard bracket, on a fixed entry set (prior winners
   came from EOD/SIGNAL exits, almost never TARGET).
5. **A5 — Opening-range / session-structure** edges the blackout may be discarding (counterfactual on
   blackout-rejected candidates).

**Deprioritised:** broader universe (Tasks 37/74S settle it), tuning `confluence_score_min` in
isolation (owner: hard gate by design), more indicator families as triggers (Task 59 "drop" list).

## 11. Strategy status

**`PRODUCTION_STRATEGY_UNCHANGED`** — `git diff 00c001b..HEAD` over
`talonx_quant/ talonx_core/ talonx_piv/ talonx_paper/ talonx_brain/ run_talonx.py talonx_ingest/` is
empty; `git diff 848de0d..HEAD` over the four quant strategy files is empty. No threshold, gate,
indicator, or decision-logic change. No new strategy promoted. No parameter selected or recommended.
Tree clean at `4b0e5dfa2415afe1dbf423c63c9cc479264106fa`.

## 12. Live status

**`NO_LIVE_SESSION_REQUIRED_FOR_TASK93`** — Task 93 was entirely offline (one deterministic
`talonx_backtest` replay + read-only analysis of existing local Alpaca data and prior artifacts). No
PAPER/live/shadow session, no broker calls, no real capital. No Task 93 finding requires live
evidence.

---

## Artifacts (`results/task93_alpha_foundation/`, gitignored)

`TASK93_CHECKPOINT.md` · `prior_research_inventory.md` · `canonical_dataset_manifest.json` ·
`canonical_dataset_report.md` · `data_quality_report.md` · `research_partitions.json` ·
`partition_rationale.md` · `baseline_metrics.json` · `baseline_trades.csv` · `cost_sensitivity.csv` ·
`funnel_decomposition.csv` · `funnel_analysis.md` · `concentration_analysis.md` ·
`outlier_robustness.csv` · `parameter_stability.md` (+ `parameter_stability_volatility_grid.csv`) ·
`statistical_confidence.md` · `baseline_comparators.md` · `counterfactual_forward_returns.csv` ·
`TASK94_RESEARCH_PROTOCOL.md` · `FINAL_REPORT.md`. Raw replay output + telemetry (229 MB volatility,
1.3 MB candidate, 116 MB rejections) under `baseline_segmentA/` (gitignored).

## Final action

Task 93 complete. **STOP.** Not starting Task 94, strategy tuning, local AI, live shadow testing, or
PIV alpha execution — each requires a new roadmap authorisation. Report returned to the gatekeeper.
