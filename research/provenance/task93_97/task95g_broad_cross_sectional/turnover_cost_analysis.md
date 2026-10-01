# TASK 95G — Turnover / Cost Analysis

Top-decile (~50 names), daily rebalance. Turnover = fraction of the top decile replaced vs the prior
day. Round-trip cost applied = `turnover × 2c × (k/step)`. Net@5 is the decision number; net@20 is the
mandatory stress. `EXPERIMENT_LEDGER.csv`.

| feature | daily turnover | ~avg holding | gross `top_decile_excess` k3 | net@5 k3 | net@20 k3 |
|---|---:|---:|---:|---:|---:|
| `A-rel_60d` | 0.13 | ~8 d | −20.5 | −24.4 | −43.5 |
| `C-voladj_60` | 0.13 | ~8 d | −21.5 | −25.4 | −38.2 |
| `A-rel_20d` / `C-voladj_20` | 0.21–0.22 | ~5 d | −18 to −19 | −24 to −26 | −44 to −46 |
| `A-rel_10d` | 0.30 | ~3 d | −18.8 | −27.7 | −54.2 |
| `B-pull_20_5` | 0.40 | ~2.5 d | **+3.8** | **−8.3** | −44.8 |
| `A-rel_5d` | 0.41 | ~2.4 d | −25.6 | −38.0 | — |
| `B-pull_20_3` / `D-strength_x_vol` | 0.47–0.58 | ~2 d | +2.0 / −21.7 | −12.0 / −38.9 | −44.8 / — |
| `D-relvol_20` | 0.69 | ~1.4 d | −4.9 | −25.6 | −87.5 |
| `A-rel_1d` | **0.86** | ~1.2 d | −16.1 | −41.8 | −119.2 |
| `D-vol_accel` | **0.96** | ~1 d | −3.3 | −32.2 | −87.5 |

## Reading

- **Cost is not why Task 95G fails** — 10 of 13 experiments have a **negative gross** `top_decile_excess`
  before any cost is applied. There is no gross edge to erode.
- For the 3 non-negative-gross cells (both Family B, `D-relvol_20`), the gross is +2 to +4 bps and
  turnover 0.40–0.69/day turns it firmly negative net@5. `net@20` is negative for **every** experiment.
- Turnover scales as expected with lookback (1-day rel: 0.86; 60-day rel: 0.13); the low-turnover
  long-lookback cells simply have a weak (and here negative) signal.
- **Non-overlapping 5-day rebalance** (independent forward windows): still negative for every family
  (`EXPERIMENT_LEDGER.csv` `nonoverlap5` column) — the daily-rebalance negatives are not an
  overlapping-marks artifact.

## Conclusion

The broad-universe result is a **sign / no-relationship** problem, not a cost/turnover problem.
