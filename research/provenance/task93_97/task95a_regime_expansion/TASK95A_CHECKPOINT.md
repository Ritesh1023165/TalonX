# TASK 95A — HISTORICAL REGIME EXPANSION & INTRADAY ALPHA RECHECK — CHECKPOINT

> Authoritative Task 95A memory. **After any context/session refresh: READ THIS FIRST**, then continue
> from "EXACT NEXT ACTION". Offline research/data task only — no production strategy change, no
> threshold tuning, no live session, no PIV alpha execution, no local AI, no real capital.
> Primary question: **"Does materially broader historical and regime coverage reveal a cost-robust
> long-only intraday phenomenon that was absent from the 2025-H1 discovery sample?"**

## Fixed inputs

| | |
|---|---|
| Starting SHA | `4b0e5dfa2415afe1dbf423c63c9cc479264106fa` (tree clean, verified 2026-09-03) |
| Task 93 verdict | `CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN` |
| Task 94 verdict | `ALPHA_DISCOVERY_NO_CANDIDATE_PASSED` (49 event studies, 0 pass) |
| Production strategy | UNCHANGED |
| Task 93 validation/holdout partitions | **NOT used for Task 95A exploratory mining** (frozen; poor results must not move them) |
| Universe | Task 93 35-symbol set (AAPL ADBE ADI AMAT AMD AMZN AVGO BKNG CMCSA COST CSCO GILD GOOGL HON INTC INTU ISRG KLAC LRCX MDLZ META MSFT MU NFLX NVDA PANW PEP PYPL QCOM REGN SBUX STX TSLA TXN VRTX) |

## Existing data inventory (Phase 1 — see local_history_inventory.md)

- **Every local 1-min dataset starts 2025-01-24 or later.** Zero pre-2025 history anywhere on disk.
  Confirms Task 93 §2 / Task 94 residual-risk caveat.
- Task 93 canonical (`results/task93_alpha_foundation/_canonical_data/`, 35 sym, 4,468,726 bars,
  2025-01-24 → 2026-08-14, fingerprint `796893860a…`) is Alpaca **SIP** feed, `adjustment=raw`,
  extended hours — confirmed by `results/task63r_orpb_v1_feed_remediation/feed_diagnostic.json`
  (`persisted_task63_feed: "SIP"`, omitted-feed default == SIP on this account).

## Target history (Phase 2 — pre-registered BEFORE any profitability look — see target_history_spec.md)

- **2020-01-01 → 2026-08-14**, 35-symbol Task 93 universe, Alpaca **SIP**, 1-min, `adjustment=raw`,
  extended hours — identical semantics to Task 93 canonical.
- Regimes deliberately included: 2020 COVID crash + V-recovery, 2021 bull/retail, 2022 bear/high-rate,
  2023 recovery/trend, 2024 AI-led bull, 2025 tariff-volatility (Task 94's only regime), 2026 partial.
- 10 symbols (AAPL AMD AMZN GOOGL META MSFT NVDA PYPL STX TSLA) have full span; the other 25 end
  2025-08-14 (same shape as Task 93). COMMON_UNIVERSE = the 10 deep names.

## Data acquisition status (Phase 3–4)

- **Phase 3 DECISION: `NO_DATA_PURCHASE_REQUIRED`.** Alpaca probe (`_probe_alpaca_depth.json`):
  `feed=sip` returns HTTP 200 with 1-min history back to **2016-01-01** for AAPL/STX/NVDA under the
  existing `APCA_*` credentials. `feed=iex` only reaches 2020-07-27. Task 93 used SIP, so the
  expansion uses the SAME feed — no provenance split. No `DATA_PURCHASE_PROPOSAL.md` needed.
- **Phase 4 IN PROGRESS:** `scratchpad/t95a_acquire.py` (background) — fetches 2020-01-01 → 2025-01-23
  for all 35 symbols into `_raw_expanded/<year>/<SYMBOL>.csv` (resume-safe; skips non-empty files).
  Reuses `scripts/download_historical_1m.py::download_symbol` (Alpaca path, feed omitted → SIP,
  `adjustment=raw`) — byte-identical acquisition semantics to Task 93. 2025-01-24 onward is NOT
  redownloaded; it is spliced from Task 93 canonical after a Phase-5 seam check.
  Probe timing: ~1.9 s per symbol-month, clean `check_data_quality` on AAPL 2022-06.

## Data acquisition status (Phase 4 — DONE)

- Parallel download complete: **210/210 symbol-years, 0 failures, 19,124,490 new bars**
  (`_acquire_summary.json`). Spliced with Task 93 canonical → `_expanded_data/<SYM>.csv`.
- **`expanded_dataset_manifest.json`**: `task95a_expanded_v1`, 35 sym, **25,806,723 bars**,
  2020-01-01 → 2026-08-14, fingerprint `8333c1001e28ee18…`.
- **Seam check PASSED** (`_seam_check.json`): 2025-01-24..31 re-fetched fresh for AAPL/NVDA/STX/TSLA/
  PYPL → **byte-identical** to Task 93 canonical (maxdiff 0.0). No provider/feed/adjustment seam.

## Data quality status (Phase 5 — DONE — see expanded_data_quality_report.md)

- `_quality_audit.json`: across 25.8M bars — **0 duplicates / 0 out-of-order / 0 invalid OHLC /
  0 non-positive / 0 negative volume / 0 NaN / 0 Inf.** DST: exactly 2 UTC offsets (EDT/EST), correct.
- 21 >20% consecutive-bar moves = 11 known stock splits (unadjusted step, handled) + 10 real
  earnings/news gaps (kept — the bear/high-vol regime we wanted). **No BLOCKING / no MATERIAL issue.**
  MINOR: 5 non-mega-cap split dates not day-nulled (~300/19.6M fwd-return rows).

## Regime coverage (Phase 6 — DONE — see regime_coverage_report.md)

- Feature build DONE (35 parquet parts, 2.0 GB, `_features_expanded/`). **Two builder bugs found &
  fixed** (multi-day regime-label columns only; intraday features unaffected):
  1. `mkt_bull_day`/`mkt_dd`/`mkt_ret_15m_prior`/`mkt_ret_60m_prior` were 100% NaN (tz-stripped
     `.values` reindex) — repaired `t95a_fix_regime_labels.py` + `t95a_fix_mktret.py`.
  2. `sym_dd_from_high` was split-contaminated (4:1 split read as permanent −75% drawdown) —
     repaired with split-adjusted daily series (`_regime_label_repair.json`, 11 splits detected).
- `_regime_coverage.json`: **10.7× more regular bars (19.6M), 80 months, 7 years (2020–2026)**.
  `market_drawdown > 20%`: Task 94 window 40,308 bars → expanded **2,892,659 (71.8×)** — a genuine
  index bear was essentially absent from Task 94. **Phase 6 PASS** (not INSUFFICIENT_REGIME_EXPANSION).

## Reproduction (Phase 7 — DONE — see task94_reproduction.md)

- `t95a_recheck.py repro` → `_repro_results.csv`. Every headline cut reproduces Task 94 within
  ±0.005 R on `e5` / ±0.001 R on `e0`: baseline −0.124, 1-min gate +0.013, vol-expansion +0.091,
  opening drift +0.047, close drift +0.035, relvol −0.051. **`REPRODUCTION_CONFIRMED`.**
- NOTE deviation logged: `atr_pct_1m_pctile_sym/tod` + `rv_z` use **rolling-window** rank/z-score
  (not Task 94's expanding rank) — intractable on the 10×-longer series. Feeds only the 2 A1
  symrel/todrel cuts (decisive FAILs in Task 94) + regime labels; headline cuts unaffected.

## Experiments (Phases 8–13 — DONE)

- `t95a_recheck.py full` → `expanded_experiment_results.csv` (34 cuts, **0 PASS**) + `yearly_results.csv`
  (245 rows) + `regime_results.csv` (315 rows, 9 regimes) + `common_universe_results.csv` (0 PASS) +
  `cost_sensitivity.csv` + `outlier_robustness.csv`.
- **Full history 2020–2026:** nothing clears `e5` ≥ +0.15 R. Best A1 cut `vol_expansion≥2×` = +0.038.
  Opening drift **weakened** to +0.007 (Task 94: +0.048). A4 `mkt_up ≡ mkt_down` to 4 dp (clean null).
- **Bear/high-vol regimes (the point of the task):** `trend_bear` / `market_dd>10%` / `realized_vol_high`
  opening-drift `e5` = +0.02…+0.09, negative by 10 bps; `realized_vol_high` WORSE than baseline; 2022
  full-year opening drift +0.003. **No long edge in the regimes Task 95A was built to test.**
- **Phase 12 — `t95a_phase12_13.py` (`_phase12_13_vollow.json`):** the ONLY promising slice is the
  **low realized-vol regime** (`rv_z ≤ −0.85`). `opening×vol_low` `e5` +0.207 / `open30_up15×vol_low`
  +0.310 / `volexp×vol_low` +0.201 — broad, un-concentrated, positive every year 2020–2026, survive
  the FULL outlier battery (exclude-April, rm-best-1/3/5/sym/month/year, both halves). **All fail C8**
  (cost burden 0.31–0.32 ≫ 0.20 cap) and are negative/≈0 by 10 bps. `atr_pct_1m≥0.25×vol_low` n=3,162
  mechanically PASSes but is **rejected**: not frequent/broad, tail-driven (e5 +0.32 on 2020-22 bulk
  vs +1.05 on n=348 post-2022), concentrated (23%/23%/43% best sym/month/year), not pre-registered
  (1-of-~300 cut×regime cells; pre-registered A1 gate FAILED on full history).

## RESULT: `INTRADAY_ALPHA_NOT_SUPPORTED_ACROSS_EXPANDED_REGIMES`

Broader history + explicit bear/high-vol/low-vol regime conditioning confirms the **same
cost-vs-magnitude wall** as Tasks 93/94. Regime expansion did NOT explain Task 94's negative result:
(1) bear/high-vol regimes offer nothing; (2) the strongest Task 94 effect got *weaker* with more
data; (3) the one regime that helped (low-vol) hits the same C8/10-bps cost wall. Binding constraint
= long-only intraday forward drift ≈ 5 bps/30min ≈ one round-trip cost, across every regime in 6.6y.

**Next-roadmap recommendation (NOT started):** stop 1-min/intraday feature mining; pivot to
`LONGER_HORIZON / SWING ALPHA RESEARCH` under new gatekeeper authorization. Expanded 2020–2026 SIP
dataset (`_expanded_data/`) is reusable for it.

## Blockers

- None. Task 95A complete.

## EXACT NEXT ACTION

Task 95A finished; result returned to gatekeeper. **Do NOT start** independent validation, swing /
longer-horizon research, strategy modification, live shadow, PIV alpha paper execution, local AI, or
model training — each needs new roadmap authorization. If resumed: nothing to do; `FINAL_REPORT.md` +
all 13 required artifacts complete; tree clean at `4b0e5df`; 0 residual processes.
