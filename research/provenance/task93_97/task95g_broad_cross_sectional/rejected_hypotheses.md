# TASK 95G — Rejected Hypotheses

**13 experiments (exact replication of Task 95E Families A–D), 0 `DISCOVERY_PASS`, 13 `DISCOVERY_FAIL`.**
No composites run (early-stop gate fired). Metric = `top_decile_excess` = mean(top-10% bucket
`fwd_kd`) − equal-weight eligible-member universe `fwd_kd`, bps, market drift removed by
construction; net@5 turnover-adjusted. Universe = historically-correct point-in-time S&P 500 (~498
eligible names/date, 819 discovery ranking dates). Full numbers: `EXPERIMENT_LEDGER.csv`.

## Baseline cross-sectional dispersion

Mean daily cross-sectional SD of `fwd_kd`: **188 / 402 / 628 / 1011 bps** at 1/3/5/10d. Any effect
found (≤ ±26 bps) is < 0.06 SD of the idiosyncratic spread.

## Family A — relative momentum (6 exp, all FAIL)

| lookback | k3 `top_decile_excess` / net@5 | symbol-block CI | why |
|---|---:|---|---|
| rel 1d | −16.1 / −41.8 | [−21.1, −11.3] | **significantly negative** (reversal), 0/4 years, huge turnover |
| rel 3d | **−26.3** / −42.1 | **[−32.6, −20.5]** | significantly negative, monotone reversal gradient (D1 −26 → D10 +27), T−B −53 |
| rel 5d | −25.6 / −38.0 | [−32, −19] | significantly negative |
| rel 10d | −18.8 / −27.7 | **[−25.3, −12.7]** | **inverts Task 95E's +27.9** — the near-miss does not replicate |
| rel 20d | −17.9 / −24.3 | [−24.6, −11.1] | negative, 0/4 years |
| rel 60d | −20.5 / −24.4 | [−27, −14] | negative, 0/4 years |

**Ruled out (with a sign):** cross-sectional relative strength is a **negative-excess (short-term
reversal)** predictor at 1–10 days on a broad universe. Not a long-only edge. Task 95E's positive was
a 7-mega-cap concentration + survivorship artifact.

## Family B — pullback within relative strength (2 exp, all FAIL)

| feature | k3 `top_decile_excess` / net@5 | why |
|---|---:|---|
| `pctrank(rel20) − pctrank(rel3)` | +2.0 / −12.0 | G2 (net negative), G4 (CI straddles 0), G5 (1/4 yrs), G7 (non-monotone) |
| `pctrank(rel20) − pctrank(rel5)` | +3.8 / −8.3 | best cell in the task; symbol CI **[−0.2, +8.1]** ≈ 0; T−B +17 < +20; net@10 −20.5; D2 bump not D1; 2/4 yrs |

**Ruled out:** a real but tiny reversal-flavoured tendency, economically worthless after turnover,
statistically ≈ zero, non-monotone, not year-stable.

## Family C — volatility-adjusted relative strength (2 exp, all FAIL)

| feature | k3 `top_decile_excess` / net@5 | why |
|---|---:|---|
| `ret20 / rv20` | −18.8 / −25.5 | significantly negative (CI [−23.6, −13.1]), monotone reversal, 0/4 yrs |
| `ret60 / rv60` | −21.5 / −25.4 | significantly negative, 0/4 yrs |

**Ruled out:** vol-scaling is the same momentum signal; no incremental information; same negative sign.

## Family D — relative volume / attention (3 exp, all FAIL)

| feature | k3 `top_decile_excess` / net@5 | daily turnover | why |
|---|---:|---:|---|
| `vol_ratio_20` | −4.9 / −25.6 | 0.69 | **flat decile gradient** (−5 to −8 all buckets) = no rank info; cost kills it |
| `vol_ratio_20 / prior` | −3.3 / −32.2 | 0.96 | ~full daily churn, no gross signal |
| `pctrank(rel5) + pctrank(vol_ratio_20)` | −21.7 / −38.9 | 0.58 | inherits Family A's negative momentum + adds turnover |

**Ruled out:** relative volume / attention carries no cost-survivable cross-sectional ranking value.

## Early-stop gate — fired

No family shows a monotone *long-direction* gradient; `top_minus_bottom` is negative (A, C), ≈ 0 (D),
or +17 < +20 (B); no positive turnover-adjusted `top_decile_excess`. **STOP before composites.**
Per the protocol, no ML fallback and no new factors.
