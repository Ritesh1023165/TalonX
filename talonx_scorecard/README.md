# talonx_scorecard

Offline research package for `TICKER_SCORECARD_V1`. Spec: `docs/research/preregistration/2026-11-03_ticker_scorecard_v1.md`
(commit `4a3bec3125e181baea695dab3f2bebb1f9037395`). Do not edit `config.py` after approval; every run records
`config.spec_fingerprint()`.

## Built
| Module | Purpose |
|---|---|
| `config.py` | Locked constants: horizons, segments, 12 features, costs, gate thresholds, spec fingerprint |
| `labels.py` | SPY-excess labels, rank dates, purged TRAIN / VALIDATE / HOLDOUT membership |
| `splits.py` | Split-adjustment check for data gate 1 |
| `gates.py` | The four data gates (`DATA_NOT_READY` if any fails) |
| `panel.py` | Pure transforms: bars to wide frames, universe floor, split parsing, panel SHA-256 |
| `alpaca_fetch.py` | Alpaca bars and split fetch (network; run where the keys are) |
| `../scripts/scorecard_build_panel.py` | Phase 1 runner: builds the panel, runs gates 1 and 2, writes `results/scorecard_v1/panel/gate_report.json` |

## Next (in order)
1. Run `scripts/scorecard_build_panel.py` on the machine with the keys (smoke test with `--max-symbols 60` first).
2. SEC bulk-file stage (XBRL with filing times, Form 4): needed for gates 3 and 4, which report NOT_RUN until then.
3. `features.py` (F1–F12), `score.py` (EQ and RIDGE, one `score(panel, date)` used by backtest and live), `evaluate.py` (G1–G5).

No outcome (return, IC, hit rate) may be computed before all four data gates pass.
