# TASK 95B — Phase 1 — Aggregation Specification

Source: `task95a_expanded_v1` (Alpaca **SIP** 1-minute bars, `adjustment=raw`, extended hours, UTC
tz-aware) at `results/task95a_regime_expansion/_expanded_data/<SYM>.csv`. Fingerprint
`8333c1001e28ee18…`. **Not redownloaded.** The 1-minute source is retained unchanged.

Builder: `scratchpad/t95b_build_daily.py` → `_daily/<SYM>.csv`, `_daily_all.parquet` (51,922 rows),
`_intraday_bridge.parquet` (51,836 rows), `aggregated_dataset_manifest.json` (`task95b_daily_v1`).

## Daily bar construction

| Rule | Value |
|---|---|
| Session | **Regular session only**: `570 ≤ et_min < 960` (09:30–16:00 America/New_York), Mon–Fri. Pre/after-hours excluded from the daily bar. |
| Timezone | Bars carried in UTC; the trading-day label is the `America/New_York` calendar date of the bar. |
| DST | Handled by `tz_convert("America/New_York")` before taking the calendar date and minute-of-day — the same mechanism Task 95A verified produced exactly two UTC offsets (EDT/EST) with no misalignment. |
| Bar fields | `open` = first regular 1-min bar's open; `high` = max regular high; `low` = min regular low; `close` = last regular 1-min bar's close; `volume` = Σ regular 1-min volume; `n_min_bars` = count. |
| Partial / short days | A day is kept only if it has **≥ 60 regular 1-min bars**. Half-days (early close) that clear that bar are kept as-is (their `last_etm` < 960 is recorded); no synthetic fill. |
| Overnight boundary | The daily bar never spans midnight — it is one ET calendar day's regular session. `overnight_gap` = `adj_open(t) / adj_close(t−1) − 1`; `fwd_overnight` = `adj_open(t+1) / adj_close(t) − 1`. |
| Missing days (holidays, halts) | Simply absent — the series is the set of days that traded. Forward horizons count **trading days**, not calendar days (see `forward_horizon_spec.md`). |
| Delisted / unavailable | None in the 35-symbol universe over 2020–2026 (Task 95A confirmed continuous listing). |

## Split adjustment

Unadjusted SIP prices step at each split ex-date. Detection: on the daily raw-`close` series, any
consecutive-day ratio `> 1.35` or `< 1/1.35` whose magnitude is within 15 % of a standard ratio
(2,3,4,5,7,10,15,20) is treated as a split. The cumulative factor **divides every price strictly
before the ex-date** (a 4-for-1 down-split multiplies pre-split prices by 0.25). `adj_open/high/low/close`
carry the adjusted series; raw OHLCV is retained alongside; `split_factor` and `is_split_day` are
recorded per row.

**11 splits detected across 9 symbols** (identical to Task 95A's audit):
AAPL 2020-08-31 (4:1) · AMZN 2022-06-06 (20:1) · AVGO 2024-07-15 (10:1) · GOOGL 2022-07-18 (20:1) ·
ISRG 2021-10-05 (3:1) · LRCX 2024-10-03 (10:1) · NVDA 2021-07-20 (4:1) & 2024-06-10 (10:1) ·
PANW 2022-09-14 (3:1) & 2024-12-16 (2:1) · TSLA 2020-08-31 (5:1) & 2022-08-25 (3:1).

Forward returns (`fwd_{1,2,3,5,10}d`, `fwd_{1,2,3,5,10}d_minlow`) that would **span a split ex-date
are set to NaN** (a return crossing an unadjusted step, even after per-side adjustment, is not
trusted). Nulled counts scale with horizon (47 for 1d … 470 for 10d out of 51,922) — consistent with
11 splits × ~1–2 symbols × horizon.

**Volume is NOT split-adjusted** (raw share volume). All volume features are *ratios* to a trailing
20-day median of the same series, so a split step self-cancels within ~20 days; the split day itself
and the ~19 days after carry a distorted `vol_ratio_20` and are flagged via `is_split_day` + the
20-day window. Not used as a hard gate anywhere.

## Causal features on the daily bar (all use only completed prior days)

`ret_1d`, `overnight_gap`, `intraday_o2c`; `ret_{3,5,10,20,60}d_prior` (shifted +1 day);
`sma20/50/200` + `above_sma20/50/200` (shifted); `atr14` (Wilder, adjusted TR) + `atr_pct` (shifted);
`rv20`, `rv60` (std of daily returns, shifted); `hi20/lo20/hi60`, `close_vs_hi20`, `range_pos_20`,
`dd_from_hi_all` (shifted); `rsi14_d` (daily Wilder RSI on `adj_close`, shifted); `vol_ratio_20` +
`vol_ratio_20_prior`.

## Intraday-bridge view (transitional — NOT a reopening of 5–30 min mining)

From a fixed **10:00 ET** entry (the last 1-min close at `et_min ≤ 600`, required to print within
598–605), same-session forward returns to **11:00 / 12:00 / 14:00 ET** (`fwd_60m/120m/240m`). One row
per (symbol, trading day). Used only in the Phase 3 cost-to-move scan.

## Validation (vs raw 1-minute, sample)

| Date | Raw O/H/L/C (regular) | Daily O/H/L/C | `adj_close` | `split_factor` | `n_min_bars` |
|---|---|---|---|---|---|
| AAPL 2021-03-15 | 121.39/124.00/120.42/124.00 | identical | 124.00 | 1.0000 | 390 |
| AAPL 2022-06-13 | 132.85/135.20/131.44/131.88 | identical | 131.88 | 1.0000 | 390 |
| AAPL 2024-01-05 | 181.94/182.76/180.17/181.18 | identical | 181.18 | 1.0000 | 390 |
| AAPL 2020-08-28 (pre-split) | 504.03/505.77/498.31/498.82 | identical | **124.70** | 0.2500 | 390 |
| AAPL 2020-08-31 (split day) | 127.62/131.00/126.00/128.85 | identical | 128.85 | 1.0000 | 390 |

`fwd_5d` cross-checked against a manual `adj_close[t+5]/adj_close[t] − 1` — exact match. `ret_1d`
across the 2020-08-31 split boundary = +3.32 % (128.85 / 124.705 − 1) — correct on adjusted prices.
`fwd_5d` on the 5 days preceding each split ex-date = NaN as designed.

Coverage: 51,922 trading-day rows, 35 symbols, 2020-01-02 → 2026-08-14, ~8,800 rows/year 2020–2024,
tapering 2025–2026 as the 25 non-deep names end 2025-08-14 (COMMON_UNIVERSE = 10 deep names).
