# TASK 93 — Alpha Research Foundation & Frozen Baseline — CHECKPOINT

> Authoritative Task 93 memory. **After any context/session refresh: READ THIS FILE FIRST**, then
> continue from "EXACT NEXT ACTION". Do not repeat completed phases. Offline research only — no live
> session, no strategy change, no tuning, no real capital, no local AI by default.

## Phase 0 — Research checkpoint

| | |
|---|---|
| Branch | `research/talonx-strategy-validation` |
| HEAD | `4b0e5dfa2415afe1dbf423c63c9cc479264106fa` |
| Upstream | `origin/research/talonx-strategy-validation` @ `4b0e5df…` — **HEAD == upstream**, 0 ahead / 0 behind |
| `git status --short` | empty (clean) |
| Parent | `00c001b8a5785ddf3e563dcb9eee2dbb13065253` |
| Task 92 verdict | `FULL_LIFECYCLE_QUALIFICATION_PASS` |
| **Strategy-freeze confirmation** | `git diff 00c001b..HEAD -- talonx_quant/ talonx_core/ talonx_piv/ talonx_paper/ talonx_brain/ run_talonx.py talonx_ingest/` → **empty**. Also `git diff 848de0d..HEAD -- talonx_quant/strategy.py talonx_quant/indicators.py talonx_quant/consumer.py talonx_quant/config.py` → **empty** — i.e. the quant strategy semantics are byte-identical to what **Task 74S** (commit `848de0d`, 2026-08-27) ran. |

### Historical datasets discovered (all local, all gitignored under `/data/`, provider = Alpaca 1-min OHLCV)

| Dataset dir | Symbols | Period | Bars | Notes |
|---|---|---|---|---|
| `task63_orpb_v1_validation` | **35** | 2025-01-24 → 2025-05-05 | ~1.31M | contiguous; universe == PIV DEFAULT_UNIVERSE |
| `task61r_fprc_v1_validation` | **35** (identical set) | 2025-05-06 → 2025-08-14 | ~1.26M | contiguous continuation of the above |
| `task7b_alpaca_long_history` | 10 (AAPL AMD AMZN GOOGL META MSFT NVDA PYPL STX TSLA) | 2025-08-15 → 2026-08-14 | ~1.90M | the long-standing "canonical baseline" universe (Task 4/7B→26→36→74S) |
| `task54_extended_windows` | 25 | W1 2025-09-15→10-24, W2 2025-11-12→12-24, W3 2026-04-07→05-18 | 111 MB | reserved validation windows |
| `task56_holdout` | 16–25 | H1 2025-12-11→01-26, H2 2026-02-06→03-20, H3 2026-05-27→07-09 | 73 MB | reserved holdout (family track) |
| `task37_universe_windows` | 25 | A 2025-08-29→09-12, B 2026-02-06→02-20, C 2026-07-20→07-31 | 38 MB | |
| `task53_warmup_windows`, `task46_validation_windows` | 24–25 | short windows late-2025 / 2026 | 38 / 20 MB | |
| `task22_oos` | 10 | 2026-08-17 → 2026-08-19 (PARTIAL) | small | |
| `data/historical_1m/{AAPL,AMD,META,NVDA,TSLA}.csv` | 5 | ~2026-08-10 → 08-15 | tiny | smoke fixtures |

**Date range available: 2025-01-24 → 2026-08-19. No 2023–2024 data exists.** Provider = Alpaca throughout.
Broadest contiguous broad-universe stretch: **35 symbols, 2025-01-24 → 2025-08-14** (task63 ⧺ task61r).
10-symbol coverage extends to 2026-08-14 (task7b).

### Known gaps / risks
- No pre-2025 history → cannot cover multiple *years* / a 2022-style bear or 2020-style crash regime.
- The 35-symbol contiguous window is ~6.7 months (one broad regime — 2025 H1 rally/chop).
- Window datasets (task37/46/53/54/56) are **non-contiguous snapshots**, not a continuous series.
- NB-7 (yfinance) — does NOT affect these datasets (all Alpaca, already downloaded, `status:FULL`). Not a research blocker. Confirmed in Phase 2/3.
- **Prior evidence predicts near-zero trades:** Task 74S (same strategy semantics) → 0 trades over the 10-symbol year; Task 37 (35-symbol) → `LIKELY_TOO_SPARSE`; Task 26/36 (earlier, more permissive strategy) → 26 then 7 trades, edge not cost-robust.

## Phase status

| Phase | State |
|---|---|
| 0 Research checkpoint | ✅ this file |
| 1 Inventory existing research | ✅ `prior_research_inventory.md` — full arc Tasks 3–74S classified; every long-only economic eval to date shows **no cost-robust edge**; current frozen strategy == Task 74S (`strategy_version 2ae6216bca70`, 0 trades / 1.9M bars) |
| 2 Canonical dataset definition | ✅ `canonical_dataset_manifest.json` + `canonical_dataset_report.md` — `task93_canonical_v1`: 35 sym, 4,468,726 bars, 2025-01-24→2026-08-14, fingerprint `796893860a…`. No download; existing Alpaca data. |
| 3 Data quality audit | ✅ `data_quality_report.md` — 0 structural defects across 4.47M bars; 1 MINOR pre-market bad print (AMD 2025-10-06 12:07 UTC, data left unmodified); no BLOCKING issue |
| 4 Freeze partitions | ✅ `research_partitions.json` + `partition_rationale.md` — discovery 2025-01-24→08-14 (35 sym / 2,565,682 bars), validation 2025-08-15→2026-02-28 (10 / 988,278), holdout 2026-03-01→08-14 (10 / 914,766, UNTOUCHED); frozen |
| 5 Current strategy baseline replay | ✅ **DONE** (~10 h, finished 2026-09-03 02:12) — Segment A: 2,565,682 bars, `strategy_version 2ae6216bca70`, `config_hash 32a7c5b4732e`, `dataset_hash ad82c9bb459d`, deterministic. **7,647 candidates → 1 signal → 1 trade** (PYPL 2025-04-30, +5.99 R @ 0 bps, EOD exit). `baseline_metrics.json`, `baseline_trades.csv`. Segment B = Task 74S (0 trades). |
| 6 Cost sensitivity | ✅ `cost_sensitivity.csv` — n=1, cost-invariant derivation: +5.99→+5.00 R across 0/2/5/10/20 bps. **N/A for conclusions** (one +6R outlier). |
| 7 Full funnel decomposition + counterfactual | ✅ `funnel_decomposition.csv` + `funnel_analysis.md` + `counterfactual_forward_returns.csv` — two walls (vol gate 92.8% / confluence gate 99.5%). **Counterfactual:** vol-gate-rejected bars have ≈0 forward edge (removes noise, not profit); confluence-≥2 survivors (n=15) had +114 bps/15min 80% hit vs +9 bps/52% for rejected — genuinely selective but fades by EOD, tiny sample. |
| 8 Concentration | ✅ `concentration_analysis.md` — trade-level degenerate (n=1: 100% PYPL/Apr-2025/RSI). Candidate-level: **49.9% of candidates from April 2025 alone**. |
| 9 Outlier dependence | ✅ `outlier_robustness.csv` — remove the 1 trade → 0. Degenerate. |
| 10 Parameter stability (no tuning) | ✅ `parameter_stability.md` + `parameter_stability_volatility_grid.csv` — sparsity structurally stable; 0.25% floor at p90–p95; nothing scores >2 confluence. No param selected. |
| 11 Statistical confidence | ✅ `statistical_confidence.md` — n=1 → no CI/bootstrap possible; trade ≈+1.2σ above random-entry mean (inside noise). |
| 12 Baseline comparators | ✅ `baseline_comparators.md` — buy&hold basket +6.24% (market was UP); random eligible long 50.2% hit / ~0 mean; TalonX trade not distinguishable from one lucky random entry. |
| 13 Strategy edge verdict | ✅ **`CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN`** — see `FINAL_REPORT.md` §1. Not SUPPORTED (n=1, no breadth/power). Not REJECTED (no negative edge; ≈never trades). Not BLOCKED (data clean, engine ran). |
| 14 Task 94 research protocol | ✅ `TASK94_RESEARCH_PROTOCOL.md` — hypothesis format, 10 numeric pass/fail criteria, anti-fishing rules, append-only ledger, 5 ranked areas (A1 volatility-regime instrument #1). |
| FINAL_REPORT | ✅ `FINAL_REPORT.md` — all 12 required sections; `PRODUCTION_STRATEGY_UNCHANGED`, `NO_LIVE_SESSION_REQUIRED_FOR_TASK93`. |

## RESULT: `CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN`

The current frozen strategy produces **1 trade across all available history** (~4.47M bars / 35 sym /
18.7 mo): Segment A 1 trade, Segment B (Task 74S) 0 trades. No trade population → no edge assessable in
either direction. NB-7 (yfinance) not a research blocker (all data pre-downloaded Alpaca). Strategy
byte-unchanged. No live session. No Task 94 / tuning / AI started.

## Experiments completed
- Smoke replay (3 sym, 2025-02-01..14, 19,945 bars): 0 trades. Confirms engine + expectation.
- **Baseline replay Segment A** (35 sym, 2025-01-24..2025-08-15, 2,565,682 bars, ~10 h): 1 trade, +5.99 R @ 0 bps.
- Counterfactual forward-return analysis on vol-gate + confluence-gate rejected populations.
- Volatility-threshold pass-rate sensitivity (from telemetry, no re-run).
- Buy-and-hold + random-eligible-long comparators.

## Blockers
- none. Task 93 complete.

## EXACT NEXT ACTION
Task 93 is finished and returned to the gatekeeper. **Do not start Task 94, strategy tuning, local AI,
live shadow testing, or PIV alpha execution** — each needs a new roadmap authorization. If resumed:
nothing to do; the FINAL_REPORT + all 19 artifacts are complete.

## Tooling notes
- `python -m talonx_backtest --data <dir> --symbols … --start … --end … --cost-sensitivity --research-telemetry`
  — deterministic frozen-strategy replay; `--cost-sensitivity` built-in grid is `[0,5,10,20]` bps
  (need a separate run / derivation for **2 bps**); `--research-telemetry` writes per-bar volatility-gate
  + per-candidate-signal CSVs. `docs/backtesting.md` documents it.
- `.venv/Scripts/python.exe` for everything (system python lacks deps).
- Prior replays of the full 1.9M-bar / 10-symbol dataset took ~3.5–4.3 h each.
