# TASK 95G — Statistical Confidence

Both bootstraps run for every experiment (Task 95E's 35-name result lacked the symbol-block test —
it is mandatory here and is what would have killed 95E's `rel_10d`):

1. **date-block bootstrap** — resample the 819 discovery ranking dates in 10-day blocks, 2000 iters
   (seed `95_070_003`).
2. **symbol-block bootstrap** — resample the ~500 eligible symbols with replacement, 2000 iters.
3. **non-overlapping 5-day rebalance** — independent forward windows.

## Cross-sectional dispersion (broad universe)

Mean daily cross-sectional SD of `fwd_kd` on the ~500-name discovery panel: **188 / 402 / 628 /
1011 bps** at k = 1/3/5/10 — larger than the 35-name set. Any `top_decile_excess` found (≤ ~25 bps
in magnitude) is **< 0.06 SD** of the idiosyncratic spread.

## Result — the significant CIs are all NEGATIVE

| feature | k3 `top_decile_excess` | symbol-block 95% CI | date-block 95% CI | sign |
|---|---:|---|---|---|
| A-rel_3d | −26.3 | **[−32.6, −20.5]** | [−40.8, −8.8] | significantly **negative** |
| A-rel_1d | −16.1 | **[−21.1, −11.3]** | [−29.3, −3.0] | significantly **negative** |
| A-rel_5d | −25.6 | [−32, −19] | negative | significantly **negative** |
| A-rel_10d | −18.8 | **[−25.3, −12.7]** | [−33.7, +2.0] | symbol-CI negative |
| A-rel_20d | −17.9 | [−24.6, −11.1] | [−31.2, +1.4] | symbol-CI negative |
| A-rel_60d | −20.5 | [−27, −14] | negative | significantly **negative** |
| C-voladj_20 | −18.8 | [−23.6, −13.1] | [−31.3, +0.5] | symbol-CI negative |
| C-voladj_60 | −21.5 | [−27, −16] | negative | significantly **negative** |
| B-pull_20_5 | +3.8 | **[−0.2, +8.1]** | [−9.3, +18.9] | **straddles zero** |
| B-pull_20_3 | +2.0 | [−3, +7] | straddles zero | **straddles zero** |
| D-relvol_20 | −4.9 | [−10.7, +1.0] | [−20.3, +4.0] | straddles zero |
| D-vol_accel | −3.3 | [−8, +1] | straddles zero | straddles zero |
| D-strength_x_vol | −21.7 | [−27, −17] | negative | significantly **negative** |

**No experiment has a positive lower bound on either bootstrap.** The momentum / vol-adjusted
families are **significantly negative** (reversal); the pullback and relative-volume families are
**indistinguishable from zero**.

## Multiple testing

13 experiments (6 momentum lookbacks + 2 pullback + 2 vol-adj + 3 relative-volume). No correction is
needed to reach the conclusion — there is no positive candidate. The most notable finding (the
significantly negative momentum decile gradient) is robust to any correction.

## Conclusion

The broad, historically-correct S&P 500 provides **strong statistical evidence against** a positive
long-only cross-sectional price/volume ranking edge at 3–10 days: the momentum families are
significantly negative with monotone reversal gradients, and nothing else is distinguishable from
noise.
