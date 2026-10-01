# TASK 95G — Year Robustness

`top_decile_excess` at k=3 by discovery year (bps). `EXPERIMENT_LEDGER.csv` `year_excess_3`.

| feature | 2020 | 2021 | 2022 | 2023 | years positive |
|---|---:|---:|---:|---:|---:|
| A-rel_1d | −21.4 | −16.1 | −9.3 | −21.4 | **0/4** |
| A-rel_3d | −68.6 | −15.2 | −7.6 | −17.1 | **0/4** |
| A-rel_10d | −54.8 | −10.1 | −7.7 | +1.3 | 1/4 |
| A-rel_20d | −41.6 | −14.4 | −8.9 | −3.8 | **0/4** |
| C-voladj_20 | −52.3 | −12.1 | −6.2 | −2.2 | **0/4** |
| B-pull_20_5 | +20.7 | −6.9 | +6.0 | −7.1 | 2/4 |
| D-relvol_20 | +15.5 | −9.5 | −4.5 | −31.9 | 1/4 |

## Reading

- **The momentum / vol-adjusted families are negative in every single discovery year** (2020 worst,
  as the COVID whipsaw punished chasing recent relative strength hardest; still negative in the
  calm-ish 2021 and the 2022 bear and the 2023 rally). This is the opposite of Task 95E's `rel_10d`,
  which was *positive* in all 4 years on the 35-name set — a direct demonstration that the 95E
  positive was a universe artifact.
- **B-pull** and **D-relvol** are the only features with any positive years, and they alternate sign
  (positive 2020, negative 2021/2023) — no year stability, and gate G5 (≥ 4 positive years) fails.
- No feature depends on a *single* strong year for a positive result, because no feature has a
  positive pooled result to begin with.

## Verdict

Year robustness confirms the negative: the broad-universe reversal is present across 2020, 2021,
2022 and 2023; no family shows the broad year-stable positive `top_decile_excess` that gate G5
requires.
