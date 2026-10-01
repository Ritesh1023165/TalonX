# TASK 95A — Phase 7 — Task 94 Reproduction Check

**Purpose:** confirm the Task 95A analysis pipeline (independent feature build over 2020–2026, then
`t95a_recheck.py`) reproduces Task 94's conclusions when restricted to the *same* discovery window
(2025-01-24 → 2025-08-14, 35 symbols). If it does not, expanded-history numbers cannot be compared
to Task 94 (`REPRODUCTION_MISMATCH`). Machine output: `_repro_results.csv`.

## Pipeline differences vs Task 94 (declared)

| Aspect | Task 94 | Task 95A repro | Effect |
|---|---|---|---|
| `atr_pct_1m` | read from Task 93's per-bar volatility telemetry CSV | recomputed from scratch (14-period EWM of TR) | ≤ 1 % differences in gate membership |
| basket / `mkt_ret_15m_prior` | built over the discovery window only | built over full 2020–2026 then sliced | negligible except first 60 min of the window |
| `relvol_tod`, ATR%-percentiles | expanding rank | **rolling-window** rank (tractability on 10×-longer series) | affects only A1 `symrel`/`todrel` (already decisive FAILs) and A3 relvol bin edges by ~1–4 % |
| R model | `1.5×ATR%(15m)` breach stop, net at 0/2/5/10/20 bps | identical | — |
| Gates | C1–C10 | identical | — |

## Headline-cut comparison (5-bps expectancy R, primary decision metric)

| Experiment | Task 94 `e5` | T95A repro `e5` | Task 94 `e0` | T95A repro `e0` | n (T94 → T95A) | Verdict agreement |
|---|---:|---:|---:|---:|---:|---|
| `A1-baseline_all_regular` | −0.1239 | **−0.1238** | +0.0525 | +0.0525 | 1,831,759 → 1,834,559 | ✓ both FAIL (negative) |
| `A1-current_1m_gate_≥0.25` | +0.0131 | **+0.0129** | — | +0.1057 | 139,334 → 139,432 | ✓ both FAIL (C2 < +0.15; dies by 10 bps) |
| `A1-vol_expansion_≥2×` | +0.0909 | **+0.0913** | +0.3274 | +0.3279 | 80,778 → 81,113 | ✓ both FAIL — best A1 cut, still C2/C8 |
| `A5-tod_0930_1000` (opening drift) | +0.0482 | **+0.0472** | +0.2759 | +0.2752 | 142,494 → 143,544 | ✓ both FAIL — +0.28 R at 0 bps, sub-threshold at 5, negative by 10 |
| `A5-tod_1530_1600` (close drift) | +0.0361 | **+0.0352** | +0.2301 | +0.2295 | 142,612 → 143,690 | ✓ both FAIL |
| `A3-relvol_tod_5_20` | −0.0467 | **−0.0510** | — | +0.0747 | 41,862 → 47,211 | ✓ both FAIL (negative after cost) |

Every headline cut agrees within **±0.005 R on `e5`** and **±0.001 R on `e0`**; sample counts agree
within 1–13 % (the relvol bin is widest because of the expanding→rolling rank change). The
qualitative Task 94 story reproduces exactly:

- unconditional intraday long forward return is **negative after realistic cost**;
- the incumbent 1-min ATR% gate lifts gross drift to ≈ +5 bps / 30 min but that is **not
  cost-survivable** (≈ 0 R at 5 bps, negative by 10);
- **volatility expansion** is the best volatility instrument found and still fails C2/C8;
- the **09:30–10:00 ET opening drift** is the single strongest broad, non-artifact effect
  (+0.28 R at 0 bps) and still fails on magnitude (+0.047 R at 5 bps < the +0.15 bar);
- relative volume / momentum give no positive edge after 5 bps.

## `A4-mkt_up_15m` note

In the first repro run this cut returned `n=0` — the `mkt_ret_15m_prior` column was 100 % NaN (a
tz-stripped `.values` reindex bug in the basket builder, same class as the daily-label bug). Repaired
in `t95a_fix_mktret.py` (equal-weight 1-min basket, per-minute returns clipped ±10 % to remove
unadjusted split ticks, correct tz-aware merge); A4 numbers in `expanded_experiment_results.csv` use
the repaired column. Task 94's A4 result was a clean null (`risk-on ≡ risk-off`), so this does not
affect any Task 94 conclusion being reproduced.

## Verdict

**`REPRODUCTION_CONFIRMED`.** The expanded pipeline reproduces Task 94's headline numbers within
deterministic tolerance. Expanded-history results (Phases 8–13) are directly comparable to Task 94.
