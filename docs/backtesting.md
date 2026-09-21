# TalonX — Backtesting & Research

`talonx_backtest` replays historical OHLCV through the **frozen live** `talonx_quant` strategy
code. It measures TalonX; it does not change it. The research lane (`research/scripts/`) reproduces
Tasks 15-63 + 101A/B.

> Detailed asset locations, sizes, sources and reproducibility notes:
> `results/task105_repository_cleanup/backtest_preservation_manifest.md`.
> Consolidated research verdicts: `docs/RESEARCH_STATUS.md`.

## Quick start (deterministic, no market data)

```powershell
.venv\Scripts\python.exe -m talonx_backtest --data examples\data\sample_AAPL_1m.csv --symbol AAPL --tz America/New_York --out results\sample
# open results\sample\backtest_results.html
```

Outputs: `backtest_summary.{json,txt}` (profit factor, expectancy, max DD, MFE/MAE),
`backtest_equity_curve.csv`, `backtest_rejected_signals.csv`, `backtest_data_quality.json`,
`backtest_results.html`. Add `--cost-sensitivity` for the friction sweep.

## Supported datasets

| dataset | where | notes |
|---|---|---|
| sample 1-min CSVs | `examples/data/sample_*_1m.csv` (tracked) | deterministic smoke + regression |
| Alpaca **SIP** 1-min, 35 names, 2020-2026 | `results/task95a_regime_expansion/` (local, ~5 GB) | `expanded_dataset_manifest.json`; account SIP-entitled |
| split-adj daily, 35 names, 2020-2026 | `results/task95b_swing_foundation/` (local) | `aggregated_dataset_manifest.json` |
| broad daily panel, 620 names, 2019-2026 | `results/task95g_broad_cross_sectional/_daily/` (local) | survivor-bias control (incl. later-removed names) |
| point-in-time S&P membership 2019-2026 | `results/task95f_historical_universe/historical_membership_by_date.parquet` (local) + `ticker_identity_map.csv` | Wikipedia MediaWiki API, £0 |
| EDGAR earnings / filing events 2020-2026 | `results/task95c_*` / `95d_*` / `95h_*` / `95i_*` (local) | `acceptanceDateTime` + XBRL first-filed |

Regeneration: `research/scripts/task61r_download_alpaca.py` / `task63_download_alpaca.py` (SIP,
slow, provider-gated); the membership from the MediaWiki API. **The local copies are canonical —
do not delete them.**

## Methodology contract

- **Causal pre-roll** (`talonx_backtest/data.py`): indicators warm up on bars *before* the
  evaluation window; the first evaluated bar never sees a future bar.
- **Point-in-time universe**: use `historical_membership_by_date.parquet` — never today's S&P
  list for a historical date. Include delisted names with their exit-date truncation (Alpaca SIP
  `adjustment=all` covers 140/141 removed names).
- **Survivor-bias control**: the 620-name panel deliberately keeps later-removed names.
- **Transaction cost / friction** (`talonx_backtest/execution.py`, `ExecutionConfig`,
  `apply_entry_cost` / `apply_exit_cost`, `--cost-sensitivity`): the binding research finding is
  intraday drift ≈ 5 bps ≈ round-trip cost — always report net-of-cost and a 5/10/25 bps stress.
- **Train / holdout**: freeze the candidate + a temporal protocol (`research/scripts/task59_*`,
  `task60_freeze_*`, `task61r_freeze_temporal_protocol.py`) with a SHA manifest *before* touching
  the holdout window.
- **Bootstrap / concentration**: symbol-block bootstrap CIs + remove-best-year / remove-best-3-
  symbols checks (embedded in `task55`-`task58`, `task101a`, `task101b`).
- **Forward outcomes**: MFE / MAE / +30m / +60m / EOD / +1D from `talonx_signals.telemetry`
  (causal, no separate loop).

## Adding a materially new hypothesis safely

1. It must be a **new data or feature class** — not a parameter sweep of a closed lane
   (`docs/RESEARCH_STATUS.md` "What is NOT reopened").
2. Write a `preregistration.md` (question, metric, threshold, universe, window, stop rules) and
   freeze it with a SHA before running anything on the holdout.
3. Load the universe point-in-time; include delisted names.
4. Warm indicators on pre-roll only; never index into future bars.
5. Report net-of-cost with a friction stress and a concentration check.
6. A single automated "pass" is not a result — adjudicate against remove-best-year /
   does-it-replicate-on-a-broader-universe (the `95F→95G` methodology that reversed a false
   positive).

## Do not

- Change any frozen indicator formula or threshold (`docs/SAFETY_BOUNDARIES.md`).
- Recompute or overwrite a prior study's canonical outputs.
- Wire a research candidate into the live runtime.
