# TASK 95G — Decile Monotonicity

All 10 deciles reported (D1 = highest feature rank → D10 = lowest). `top_decile_excess` = decile mean
`fwd_kd` − equal-weight eligible-member mean. k = 3. `_analysis.json` `decile_excess_bps_3`.

## Family A — relative momentum (`rel_3d`)

| D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **−26.3** | −19.1 | −15.4 | −10.5 | −13.6 | +3.8 | +7.0 | +13.9 | **+34.4** | +26.7 |

**Cleanly monotone in the *reversal* direction** — highest recent relative strength → worst forward
excess; lowest → best. `rel_1d`, `rel_5d`, `rel_10d`, `rel_20d` show the same shape (D1 the most
negative decile, a rising gradient toward D9/D10). This is a *credible ranking relationship* — just
with the sign that makes it a short-side signal, not a long-only one (fails gate G-sign / G7 for a
long strategy).

## Family C — vol-adjusted (`ret20/rv20`)

| D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **−18.8** | −12.9 | −14.8 | −6.2 | −7.4 | −5.2 | −5.4 | −4.0 | +3.5 | +10.2 |

Monotone reversal, D1 worst — same as Family A.

## Family B — pullback (`pctrank(rel20) − pctrank(rel5)`)

| D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| +3.8 | **+31.3** | +16.6 | −9.4 | −3.5 | −5.5 | −4.4 | −6.4 | −9.5 | −13.2 |

**Non-monotone** — the positive excess sits in **D2**, not D1, then decays. Fails G7 (D1 must be the
max). The "signal" is not a clean gradient; it is a bump in one interior decile.

## Family D — relative volume (`vol_ratio_20`)

| D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| −4.9 | −4.3 | −4.6 | −7.0 | −3.5 | −7.8 | −8.4 | −7.3 | −6.0 | −8.2 |

**Flat** — every decile ≈ −5 to −8 bps, no gradient. Relative volume carries **no rank information**.

## Verdict

- Momentum & vol-adjusted: monotone, but in the **reversal** direction → not long-only alpha
  (and Task 95E's `rel_10d`, which spiked only at D1 with random interior deciles, fails this test
  outright — its "monotonicity" was noise).
- Pullback: non-monotone (D2 bump). Relative volume: flat.
- **No family shows a monotone gradient in the long direction that gate G7 requires.**
