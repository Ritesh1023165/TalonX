# TASK 95B — Family A — Multi-Day Momentum

**Hypothesis:** recent multi-day strength continues over a 1–5 day forward horizon (declared
direction: long the strong).

**Pre-registered bins** (discovery-period quantiles): `ret_5d_prior`, `ret_20d_prior`,
`ret_60d_prior` quintiles; 20-day relative strength vs the 35-name basket, top and bottom quintile;
within 2 % of the prior 20-day high. Primary horizon 3 d (5 d for RS / near-high). Metric = net
**excess** bps over the matched unconditional-long comparator (discovery global mean:
17.7 / 26.4 / 43.5 bps at 2 / 3 / 5 d). CIs: symbol-block bootstrap + non-overlapping subsample.

## Result — 25 experiments, 0 pass

| Bin | n | excess net @5 bps | @10 bps | non-overlap CI low | block-boot CI low | years+ | symbols+ | why it fails |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `ret_5d_prior` top quintile (q5) | 6,038 | **−28.0** | −38.0 | −37.4 | −41.6 | 0.50 | 0.17 | strong recent movers **under**perform the drift |
| `ret_5d_prior` bottom quintile (q1) | 6,041 | +6.0 | −4.0 | −0.8 | +6.5 | 0.75 | 0.66 | S2 (< +25), S3, S4 |
| `ret_20d_prior` q1 (weakest) | 5,942 | +7.1 | −2.9 | +0.2 | +3.2 | 0.75 | 0.63 | S2, S3, S7 |
| `ret_20d_prior` q5 (strongest) | 5,933 | +0.4 | −9.7 | −4.2 | −10.4 | 0.50 | 0.37 | no continuation |
| `ret_60d_prior` q1 (weakest) | 5,658 | **+20.8** | +10.8 | +6.5 | +7.9 | 0.75 | 0.71 | **best A cut** — still S2 (< +25) + S7 |
| `ret_60d_prior` q5 (strongest) | 5,651 | +3.3 | −6.7 | −8.4 | −2.3 | 0.75 | 0.40 | no continuation |
| RS-20d top quintile | 5,913 | +2.8 | −7.2 | −11.0 | −14.3 | 0.50 | 0.40 | leaders don't continue |
| RS-20d bottom quintile | 5,934 | +9.8 | −0.2 | −8.7 | −7.0 | 0.75 | 0.51 | S2, S3, S4 |
| within 2 % of 20-day high | 7,719 | **−26.6** | −36.6 | −48.1 | −38.6 | 0.25 | 0.29 | proximity-to-breakout **underperforms** |

## Interpretation

**Multi-day price momentum does not persist in this universe at swing horizons.** The clearest
patterns are the *wrong* sign for a momentum thesis: the top prior-return quintile and the
near-20-day-high population **underperform** the unconditional drift by 25–28 bps over 3–5 days
(consistent with short-term reversal / mean-reversion in mega-cap tech). The only mildly positive
cells are the *weakest* prior-return quintiles (q1) — a reversion signal, not momentum — and even
those clear the drift by only +6 to +21 bps, below the +25 economic bar, with S4/S7 problems. The
`ret_60d_prior` q1 cut (+20.8) is the family best; it is a slow-timescale reversion (bought-the-
laggards) and it still fails S2 and concentrates (S7). No momentum candidate advances.
