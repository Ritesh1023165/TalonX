# TASK 95A — HISTORICAL REGIME EXPANSION & INTRADAY ALPHA RECHECK — FINAL REPORT

## 1. Verdict

# `INTRADAY_ALPHA_NOT_SUPPORTED_ACROSS_EXPANDED_REGIMES`

Materially broader history (2020-01-01 → 2026-08-14, **25.8 M bars**, seven distinct macro regimes
including the 2020 COVID crash and the 2022 bear) **does not** reveal a cost-robust long-only
intraday phenomenon that Task 94's 2025-H1 sample hid. Every pre-registered A1–A5 phenomenon family,
re-checked across the expanded history and conditioned on deterministic, causally-identifiable
regimes, hits the **same wall Tasks 93 and 94 hit: forward-drift magnitude (~5 bps / 30 min) ≈
round-trip transaction cost.** Zero `DISCOVERY_PASS` candidates under the frozen economic/robustness
criteria.

The one place regime expansion helped — the **low-realized-volatility regime** — produced a
*cleaner and roughly 2× larger* version of Task 94's opening-drift effect (+0.53 R at 0 bps,
positive in every year 2020–2026, survives the full outlier battery). But its **cost burden is
unchanged**: it decays to +0.21 R at 5 bps (C8 cap is 0.20) and is **negative by 10 bps**. Same
obstacle, better lit.

`PRODUCTION_STRATEGY_UNCHANGED`. `NO_LIVE_SESSION_REQUIRED_FOR_TASK95A`. `NO_LOCAL_AI_REQUIRED`.
Task 93 validation/holdout partitions were **not** used for exploratory mining.

## 2. Expanded dataset

| | |
|---|---|
| Period | **2020-01-01 → 2026-08-14** (~6.6 years) |
| Provider / feed | Alpaca **SIP**, `adjustment=raw` (unadjusted) — **identical** semantics to Task 93 canonical (`task63r` diagnostic: `persisted_task63_feed = SIP`) |
| Universe | Task 93 35-symbol set (unchanged). COMMON_UNIVERSE = 10 deep names (AAPL AMD AMZN GOOGL META MSFT NVDA PYPL STX TSLA), full span |
| Bars | **25,806,723** total; 19,585,109 regular-session. Acquired this task: 2020-01-01 → 2025-01-23 (19.1 M new bars, 210/210 symbol-years, 0 failures). Spliced from Task 93 canonical: 2025-01-24 → 2026-08-14 |
| Fingerprint | `sha256 8333c1001e28ee18…` (`expanded_dataset_manifest.json`) |
| Cost | **$0 — `NO_DATA_PURCHASE_REQUIRED`.** The existing Alpaca account is already SIP-entitled back to 2016; no new subscription. |
| Seam | 2025-01-24 → 01-31 re-fetched fresh for 5 symbols → **byte-identical** to Task 93 canonical (`_seam_check.json`, maxdiff 0.0) |
| Quality | 0 duplicates / 0 out-of-order / 0 invalid OHLC / 0 bad prices / 0 negative volume / 0 NaN / 0 Inf across 25.8 M bars. DST correct (2 offsets). 11 stock splits (handled) + 10 real earnings gaps (kept). No BLOCKING/MATERIAL issue. (`expanded_data_quality_report.md`) |

## 3. Regime diversity vs Task 94

`regime_coverage_report.md` / `_regime_coverage.json`. Labels are deterministic, causal, computed on
**split-adjusted** daily series, and never derived from strategy P&L.

| Regime | Task 94 window (bars) | Expanded (bars) | × |
|---|---:|---:|---:|
| Regular-session total | 1,834,898 | 19,585,109 | **10.7×** |
| Distinct calendar months | ~7 | 80 | 11× |
| `trend_bear` | 845,384 | 8,337,097 | 9.9× |
| `realized_vol_high` | 334,832 | 3,647,906 | 10.9× |
| `market_bear_day` | 634,357 | 5,907,004 | 9.3× |
| **`market_drawdown > 20%`** | **40,308** | **2,892,659** | **71.8×** |

A genuine index-level > 20 % bear was **essentially absent** from Task 94's data. 2022 is now fully
represented (the only year where trend-bear bars > trend-bull). **Phase 6 passed** — this is not
`TASK95A_INSUFFICIENT_REGIME_EXPANSION`.

## 4. Task 94 reproduction (comparability gate)

`task94_reproduction.md` / `_repro_results.csv`. The Task 95A pipeline, restricted to Task 94's exact
discovery window, reproduces **every** headline cut within **±0.005 R on the 5-bps metric** and
**±0.001 R on the 0-bps metric**:

| cut | Task 94 e5 | T95A repro e5 |
|---|---:|---:|
| baseline_all_regular | −0.1239 | −0.1238 |
| current_1m_gate ≥0.25 | +0.0131 | +0.0129 |
| vol_expansion ≥2× | +0.0909 | +0.0913 |
| opening drift 09:30–10:00 | +0.0482 | +0.0472 |
| close drift 15:30–16:00 | +0.0361 | +0.0352 |
| relvol_tod 5–20× | −0.0467 | −0.0510 |

**`REPRODUCTION_CONFIRMED`.** Expanded-history numbers are directly comparable to Task 94. (Two
feature-builder bugs in multi-day *regime-label* columns were found and fixed during Phase 6/7; they
do not touch intraday features or this reproduction — see checkpoint + `_regime_label_repair.json`.)

## 5. Expanded-history findings by phenomenon (full 2020–2026, 5-bps primary)

`expanded_experiment_results.csv` — **34 pre-registered cuts, 0 `DISCOVERY_PASS`.**

| Family | Best cut (full history) | `e5` | `e10` | vs Task 94 |
|---|---|---:|---:|---|
| **A1 volatility instrument** | `vol_expansion ≥ 2×` | **+0.038** | −0.201 | same shape; still the best A1 cut, still fails C2/C8 |
| A1 incumbent gate | `atr_pct_1m ≥ 0.25` | +0.022 | −0.081 | ~+2 bps, dies by 10 bps (Task 94: +0.013) |
| A1 multi-timeframe | `1m∧5m∧15m ≥ p66` | −0.059 | −0.154 | **still worse than the 1-min gate alone** |
| A3 relative volume / momentum | every bin | −0.14 … +0.005 | negative | no continuation edge (unchanged) |
| A4 market conditioning | `mkt_up_15m` vs `mkt_down_15m` | **−0.1257 vs −0.1255** | — | **risk-on ≡ risk-off, identical to 4 dp** (clean null, unchanged) |
| **A5 intraday structure** | `tod 09:30–10:00` (opening drift) | **+0.007** | −0.224 | **weakened** from Task 94's +0.048 — the effect is *smaller* over the longer history |

Over 6.6 years the opening-drift 5-bps expectancy is **essentially zero** (+0.007 R). It looked
larger in 2025 H1 by chance; it is not larger in 2020, 2022, 2023, or 2024. Common-universe
(`common_universe_results.csv`): same story, 0 PASS, opening drift +0.064.

## 6. Bear / high-volatility findings (explicit — the reason this task exists)

`regime_results.csv`. The regimes Task 95A was built to test show **no long edge**:

| Regime | opening-drift `e5` | vol-expansion `e5` | baseline `e5` |
|---|---:|---:|---:|
| `trend_bear` | +0.022 | +0.059 | −0.114 |
| `realized_vol_high` | **−0.022** | +0.019 | −0.091 |
| `market_bear_day` | +0.028 | +0.071 | −0.097 |
| `market_drawdown > 10%` | +0.035 | +0.087 | −0.090 |
| 2022 (full-year, opening drift) | **+0.003** | +0.073 | −0.101 |
| 2020 (COVID crash year, opening drift) | +0.050 | +0.082 | −0.100 |

**In the bear and high-volatility regimes the long-only intraday edge is at best ~+0.03–0.09 R at
5 bps — below the +0.15 bar and negative by 10 bps — and `realized_vol_high` is *worse* than
baseline.** The 2022 bear year in particular offers nothing (opening drift +0.003 R). Task 94's
negative result was **not** caused by missing bear/crisis coverage.

## 7. The one regime that helped — low realized volatility (Phase 12)

`_phase12_13_vollow.json`. Conditioning the A5/A1 continuation cuts on **`rv_z ≤ −0.85`** (a symbol's
trailing-quarter realized volatility well below its own norm — causal, known at bar close):

| Cut × `vol_low` | n | `e0` | `e5` | `e10` | PF@5 | cost burden (0→5) | survives full outlier battery? |
|---|---:|---:|---:|---:|---:|---:|---|
| `opening 09:30–10:00` | 32,415 | +0.526 | **+0.207** | −0.111 | 1.36 | **0.319** | **yes** (every year +, rm-best-3/sym/month/year all ≥ +0.19, both halves +) |
| `open30 ∧ prior-15m up` | 11,817 | +0.616 | **+0.310** | +0.005 | 1.55 | **0.306** | yes |
| `vol_expansion ≥ 2×` | 34,830 | +0.506 | **+0.201** | −0.105 | 1.37 | **0.305** | yes |
| `atr_pct_1m ≥ 0.25` | **3,162** | +0.590 | +0.403 | +0.216 | 1.79 | 0.187 | mechanically yes — **rejected, see below** |

The first three are **genuinely real**: broad (months-positive 0.67–0.71, symbols-positive
0.71–0.80), un-concentrated (best symbol ≤ 9 %, best year ≤ 31 % of positive R), essentially
zero April-2025 weight, **positive in every one of the seven years**, and unmoved by removing the
best event / best 3 / best 5 / best symbol / best month / best year, or by splitting 2020-22 vs
2023-26. This is a *materially cleaner and ~2× larger* opening-drift than Task 94's 2025-H1 view —
the genuine contribution of regime expansion.

**But all three fail the frozen economic criteria**: 5-bps expectancy reaches only +0.20–0.31 R
while **cost burden (0→5 bps) is 0.31–0.32 R, well over the C8 cap of 0.20 R**, and two of the three
are **negative at 10 bps**. The 0-bps effect roughly doubled under `vol_low` conditioning; the cost
did not. Net-of-realistic-cost, the edge is still too small.

### Why `atr_pct_1m ≥ 0.25 × vol_low` (n=3,162) is **not** promoted

The automated criteria check passes it (`e5` +0.40, `e10` +0.22, no C1–C10 flag). It is nonetheless
**rejected** as a candidate:

- **Not frequent / not broad.** ~3,000 events in 6.6 years ≈ 1.3 per symbol per month — a rare
  micro-condition, not a phenomenon a long-only strategy can run on. The protocol requires effects
  that "occur frequently … broad and not outlier-dependent."
- **Tail-driven.** `e5` = +0.32 R on the statistically meaningful 2020–2022 bulk (n≈2,800) but
  **+1.05 R on n=348 post-2022 events**; the "survives 10 bps" reading (+0.22 R) is inflated by that
  thin tail. Split-half e5 is +0.32 (2020-22) vs +1.05 (2023-26).
- **Concentrated at this sample size.** One symbol = 23 %, one month = 23 %, one year = 43 % of
  positive R — the automated C7 thresholds (0.4 / 0.5) are too permissive for n≈3,000.
- **Not pre-registered.** Task 95A is a *pre-registered recheck of the A1–A5 families*. This cell is
  the intersection of a pre-registered cut (which **failed** on full history, `e5` +0.022) with a
  regime slice; ≈300 (cut × regime) combinations were examined and 2–3 nominal false positives are
  expected. This is one cell.
- **Self-contradictory condition** (a transient 1-min ATR% spike ≥ 0.25 % *inside* a below-normal
  realized-vol regime) — not a coherent causal mechanism.

## 8. Common-universe findings

`common_universe_results.csv` — restricting to the 10 full-history symbols: **0 PASS**, identical
conclusions. Opening drift `e5` = +0.064 (vs +0.007 on all 35), still far below +0.15 and negative
by 10 bps. No survivorship/coverage effect is masquerading as a regime effect.

## 9. Outlier robustness

`outlier_robustness.csv`. Full-history cuts: opening drift `e5` stays ≈ +0.006 under exclude-April,
exclude-2025, remove-best-1/5, remove-best-symbol, remove-best-month — it is *robustly* ≈ zero. The
`vol_low` cuts (§7) survive the entire battery on the positive side (that is exactly why they are
interesting) but fail on cost, not on robustness. Excluding April 2025 changes nothing anywhere
(`e5` deltas < 0.002 R) — the Task 94 April-2025 artifact is diluted to insignificance in 6.6 years
and was never the point.

## 10. Final research interpretation — did lack of regime coverage explain Task 94's negative result?

**No.** Three independent lines of evidence:

1. **The bear/high-vol regimes themselves offer nothing.** 2022 (full bear year), `trend_bear`,
   `market_drawdown > 10/20 %`, and `realized_vol_high` all show long-only intraday `e5` between
   −0.02 and +0.09 R — below threshold, negative by 10 bps. `realized_vol_high` is *worse* than
   baseline.
2. **The strongest Task 94 effect got weaker, not stronger.** Opening drift: +0.048 R at 5 bps in
   2025 H1 → **+0.007 R** across 2020–2026. More data shrank it toward its true value.
3. **The only regime that helped (low realized vol) hits the same cost wall.** It ~doubles the
   0-bps effect but not the 5-bps net; cost burden 0.31 R ≫ 0.20 cap; negative by 10 bps.

The binding constraint established by Tasks 93 + 94 — **long-only intraday forward drift in this
universe is ~5 bps / 30 min, i.e. one round-trip's worth of cost** — holds across every regime in
6.6 years of data. It is a property of the instrument class and holding horizon, not of the sample.

## 11. Next recommendation (NOT auto-started)

Per the task's own interpretation clause: since Task 95A returns
`INTRADAY_ALPHA_NOT_SUPPORTED_ACROSS_EXPANDED_REGIMES`, **stop further 1-minute / intraday feature
mining**; do not launch more Task-94-style parameter or regime searches. The roadmap should pivot to
**`LONGER_HORIZON / SWING ALPHA RESEARCH`** (multi-day holding, where a few bps/day can compound
above a one-off round-trip cost) — a genuine hypothesis-space change — **subject to new gatekeeper
authorization.** The expanded 2020–2026 SIP dataset built here (`_expanded_data/`,
`expanded_dataset_manifest.json`) is directly reusable for that.

Documented-but-not-recommended: the **`opening-drift × low-realized-volatility`** effect is a real,
broad, temporally-stable phenomenon that fails *only* on cost. It would become interesting only if a
future task changes the cost assumption (e.g. demonstrated sub-3-bps round-trip execution) or the
holding horizon. It is **not** a Task-95A candidate and is **not** frozen for validation.

## 12. Production status

**`PRODUCTION_STRATEGY_UNCHANGED`.** `git diff 00c001b..HEAD` over
`talonx_quant/ talonx_core/ talonx_piv/ talonx_paper/ talonx_brain/ run_talonx.py talonx_ingest/
scripts/` is **empty**; tree clean at `4b0e5dfa2415afe1dbf423c63c9cc479264106fa`. No strategy,
indicator, threshold, gate, execution, risk, or alert change. No new strategy promoted. All Task 95A
work is offline research scripts + gitignored artifacts under `results/task95a_regime_expansion/`.

## 13. Live status

**`NO_LIVE_SESSION_REQUIRED_FOR_TASK95A`.** The only network use was Alpaca's **historical** bars
API for data acquisition (data acquisition, not live strategy validation — explicitly permitted).
No TalonX runtime launched, no PAPER/live/shadow session, no broker order calls, no real capital.
`NO_LOCAL_AI_REQUIRED` — deterministic code/statistics throughout; no `AI_USE_CASE_PROPOSAL.md`.

---

## Artifacts (`results/task95a_regime_expansion/`, gitignored)

`TASK95A_CHECKPOINT.md` · `local_history_inventory.md` · `target_history_spec.md` ·
`expanded_dataset_manifest.json` · `expanded_data_quality_report.md` · `regime_coverage_report.md` ·
`task94_reproduction.md` · `expanded_experiment_results.csv` · `yearly_results.csv` ·
`regime_results.csv` · `common_universe_results.csv` · `cost_sensitivity.csv` ·
`outlier_robustness.csv` · `FINAL_REPORT.md`. Supporting: `_probe_alpaca_depth.json`,
`_seam_check.json`, `_quality_audit.json`, `_regime_coverage.json`, `_regime_label_repair.json`,
`_repro_results.csv`, `_phase12_13_vollow.json`, `_raw_expanded/` (raw layer), `_expanded_data/`
(normalized layer), `_features_expanded/` (feature parquet parts).

## Final action

Task 95A complete. **STOP.** Not starting independent validation, swing/longer-horizon research,
strategy changes, live shadow, PIV paper alpha, or local AI — each requires a new roadmap
authorization. Result returned to the roadmap gatekeeper.
