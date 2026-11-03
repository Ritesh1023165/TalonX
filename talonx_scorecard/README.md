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

## Next (in order)
1. `panel.py`: build the point-in-time daily panel from Alpaca daily bars and SEC bulk files (run on the machine that holds the data; the sandbox has no market data or keys).
2. Run the four data gates on the real panel; commit the report.
3. `features.py` (F1–F12), `score.py` (EQ and RIDGE, one `score(panel, date)` used by backtest and live), `evaluate.py` (G1–G5).

No outcome (return, IC, hit rate) may be computed before all four data gates pass.
