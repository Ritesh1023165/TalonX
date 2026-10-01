# TASK 95G — Family C — Volatility-Adjusted Relative Strength Replication

Replication of Task 95E Family C: `ret_20 / rv_20`, `ret_60 / rv_60` (rv = trailing 20/60-day stdev
of daily returns). Top decile (~50 names), daily rebalance, 819 discovery ranking dates.

| feature | k3 `top_decile_excess` / net@5 | k5 / net@5 | k10 / net@5 | T−B (k3) | symbol-block CI (k3) | years+ | verdict |
|---|---:|---:|---:|---:|---|---:|---|
| `ret20 / rv20` | −18.8 / −25.5 | −28.4 / −39.6 | −40.7 / −63.0 | −29.0 | **[−23.6, −13.1]** | 0/4 | FAIL |
| `ret60 / rv60` | −21.5 / −25.4 | −29 / −38 | −37 / −55 | −38.2 | [−27, −16] | 0/4 | FAIL |

## Reading

Vol-adjusting the trailing return does **not** change the sign or the story — it is the same
relative-momentum signal in a different scaling. `ret20/rv20` decile gradient at k3:

| D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **−18.8** | −12.9 | −14.8 | −6.2 | −7.4 | −5.2 | −5.4 | −4.0 | +3.5 | +10.2 |

Monotone reversal, D1 worst — identical shape to Family A. Symbol-block CI on the top decile is
entirely negative; negative in all 4 discovery years; more negative among removed constituents
(current −16.4 / removed −33.9); net@10 and net@20 far negative.

## Verdict

**Family C — both `DISCOVERY_FAIL`.** Risk-adjusted relative strength carries no incremental
cross-sectional information over raw relative strength, and inherits the same negative (reversal)
sign on the honest broad universe.
