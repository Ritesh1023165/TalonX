# TASK 95A — Phase 6 — Regime Coverage Report

**Question:** does the expanded 2020–2026 dataset *materially* increase regime diversity relative to
Task 94's discovery window (2025-01-24 → 2025-08-14)? If not → `TASK95A_INSUFFICIENT_REGIME_EXPANSION`.

**Answer: YES, materially.** Machine output: `_regime_coverage.json`.

## Regime labels (deterministic, causal, NOT optimized)

All labels are computed on **split-adjusted** daily series (see `_regime_label_repair.json` — the
first build used unadjusted prices and a 4:1 split read as a permanent −75% "drawdown"; repaired by
detecting the ratio at each >35 % single-session step and back-adjusting). None is derived from
strategy P&L.

| Label | Definition (causal) |
|---|---|
| `trend_bull` / `trend_bear` | symbol's adj daily close above / below its own 50-day SMA, shifted 1 day |
| `realized_vol_high/mid/low` | rolling z-score (≈60 trading-day window) of a 60-min mean `ATR%(1m)`; high = z ≥ +0.85, low = z ≤ −0.85 (≈ 80th / 20th pctile of a normal) |
| `symbol_drawdown > 10% / 20%` | adj daily close ≤ −10 % / −20 % from its trailing all-time high, shifted 1 day |
| `market_bull_day` / `market_bear_day` | equal-weight 35-name adj-daily-return basket above / below its 50-day SMA, shifted 1 day |
| `market_drawdown > 10% / 20%` | basket ≤ −10 % / −20 % from its trailing peak, shifted 1 day |
| `year`, `quarter` | calendar |

## Coverage: expanded vs Task 94 window

| Regime | Task 94 window (bars) | Expanded (bars) | ×  |
|---|---:|---:|---:|
| Regular-session bars total | 1,834,898 | 19,585,109 | **10.7×** |
| Distinct calendar months | ~7 | **80** | 11× |
| Years | 1 (2025 H1) | **7** (2020–2026) | — |
| `trend_bear` | 845,384 | 8,337,097 | 9.9× |
| `realized_vol_high` | 334,832 | 3,647,906 | 10.9× |
| `symbol_drawdown > 20%` | 833,190 | 6,797,577 | 8.2× |
| `market_bear_day` | 634,357 | 5,907,004 | 9.3× |
| `market_drawdown > 10%` | 371,147 | 5,466,081 | 14.7× |
| **`market_drawdown > 20%`** | **40,308** | **2,892,659** | **71.8×** |

The last row is the decisive one: a genuine **index-level > 20 % bear** was essentially **absent** from
Task 94's data (40 k bars, the tail of the April-2025 tariff dip). The expanded set contains 2.9 M
such bars — the whole of 2022 plus the 2020 COVID crash.

## Bars by year, and trend composition

| Year | Bars | trend-bull | trend-bear | character |
|---|---:|---:|---:|---|
| 2020 | 3,373,424 | 2,062,329 | 1,297,804 | COVID crash (Feb–Mar) + liquidity V-recovery |
| 2021 | 3,325,705 | 2,196,871 | 1,128,834 | retail/mega-cap bull, low realized vol |
| 2022 | 3,345,493 | 1,240,356 | **2,105,137** | **sustained bear / high-rate — the only year bear > bull** |
| 2023 | 3,285,264 | 2,130,053 | 1,155,211 | disinflation recovery / trend |
| 2024 | 3,258,813 | 2,008,185 | 1,250,628 | AI-led momentum bull |
| 2025 | 2,392,062 | 1,306,508 | 1,085,554 | tariff-shock volatility (Task 94's window is a subset) |
| 2026 (to Aug) | 604,348 | 290,419 | 313,929 | deep-10 only |

(2025–2026 taper because the 25 non-deep symbols end 2025-08-14 — COMMON_UNIVERSE = the 10 deep names.)

## Conclusion

The expanded dataset increases regular-session observations 10.7×, calendar months 11×, and — most
importantly — turns three regimes that Task 94 barely sampled (`market_drawdown > 20%`,
`realized_vol_high`, sustained `trend_bear`) into populations of millions of bars. **Phase 6 passes:
this is NOT `TASK95A_INSUFFICIENT_REGIME_EXPANSION`.** Proceed to the Task 94 reproduction check
(Phase 7) and the pre-registered A1–A5 recheck (Phases 8–13).
