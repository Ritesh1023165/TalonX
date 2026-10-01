# TASK 95G — Family D — Relative Volume / Attention Replication

Replication of Task 95E Family D: `vol / vol_20d_avg` (relative volume), `(vol_ratio_20)/(prior)`
(acceleration), `pctrank(rel_5) + pctrank(vol_ratio_20)` (strength × attention). Daily only. Top
decile (~50 names), daily rebalance.

| feature | k3 `top_decile_excess` / net@5 | k5 / net@5 | k10 / net@5 | T−B (k3) | daily turnover | symbol-block CI (k3) | verdict |
|---|---:|---:|---:|---:|---:|---|---|
| `vol_ratio_20` | −4.9 / −25.6 | −10.4 / −44.8 | −25.3 / −94.1 | +3.2 | **0.69** | [−10.7, +1.0] | FAIL |
| `vol_ratio_20 / prior` (acceleration) | −3.3 / −32.2 | −? | −? | +8.1 | **0.96** | [−8, +1] | FAIL |
| `pctrank(rel5) + pctrank(vol_ratio_20)` | −21.7 / −38.9 | −? | −? | −31.1 | 0.58 | [−27, −17] | FAIL |

## Reading

- **Relative volume alone** has almost **no gross signal** — the decile gradient at k3 is flat and
  slightly negative across all ten buckets (−4 to −8 bps), no rank information. Its defining feature
  is turnover (0.69/day; acceleration 0.96/day ≈ full daily churn), so net@5 is firmly negative.
- **Strength × attention** inherits Family A's negative momentum sign and adds turnover — worst of
  both (−21.7 gross, −38.9 net@5).
- Symbol-block CIs straddle or sit below zero.

## Verdict

**Family D — all 3 `DISCOVERY_FAIL`.** Relative volume / attention provides no cost-survivable
cross-sectional ranking value on the broad universe — same conclusion as Task 95E and Task 95A.
