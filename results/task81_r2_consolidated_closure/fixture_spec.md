# `examples/data/sample_multi_trade_1m.csv` — regeneration specification

**Generator:** `scripts/gen_sample_multi_trade_1m.py` (deterministic, no
randomness). **TEST_FIXTURE_ONLY — NOT ALPHA EVIDENCE.**

## Why it was regenerated

The previous fixture's TSTW/TSTL/TSTE demo "trades" were authored around
the long/short bug (a BEARISH `macd_bearish_cross` opening a SHORT while
flat) removed in Task 24/25A, and it spanned only ~2 trading days — far
short of the ~8 the unmodified 200-bar / 15-minute HTF trend gate
(`talonx_quant/config.py:htf_sma_period = 200`) needs before it produces a
non-`None` `htf_sma_200`. Under the corrected, unmodified long-only
strategy it produced **zero** trades, xfailing 10 tests and forcing 1
skip.

## Construction

The strategy is **not touched**. The generator writes only OHLCV *input*
bars; the backtest engine derives every trade.

1. **Shared pre-entry sequence** — the exact bar sequence of
   `examples/data/sample_AAPL_trade_1m.csv` (a Task 73S fixture proven to
   produce one genuine `macd_bullish_cross` long entry) from
   `2025-12-23 09:30` through the entry bar `2026-01-06 10:48`. This is
   byte-identical across all three symbols (only the `symbol` column
   changes), so the engine computes an identical entry for each:

   | field | value |
   |---|---|
   | signal | `macd_bullish_cross`, `confluence_score` 2, `volume_surge_ratio` 2.545 |
   | entry price | 96.1226 |
   | stop price | 95.135234796188 (engine ATR_FALLBACK; `gross_R == -1` exactly at this level) |
   | target price | 99.57749999999999 |
   | risk_reward_ratio | 3.4991 (≥ `min_risk_reward_ratio` 1.5) |

2. **Per-symbol post-entry path** (bars from `10:49` on):

   | symbol | path | exit |
   |---|---|---|
   | `TSTW` | unchanged AAPL recovery tail (rises past the target) | **TARGET** @ 99.5775, `gross_R = +3.4991` |
   | `TSTL` | steps down ~-0.25/bar; the 5th bar's low pierces the stop | **STOP** @ 95.1352, `gross_R = -1.0000` |
   | `TSTE` | drifts up to ~98.00 (highs < target, lows > stop) and holds flat every minute through `15:55` | **END_OF_SESSION** @ 98.00 via the 15:50 ET EOD flatten, `gross_R = +1.9014` |

## Verified outcome (`python scripts/gen_sample_multi_trade_1m.py --verify`)

```
trades: 3
  TSTL  entry=96.1226 stop=95.1352 target=99.5775 exit=95.1352 reason=STOP           gross_R=-1.0000 confluence=2 rr=3.499
  TSTW  entry=96.1226 stop=95.1352 target=99.5775 exit=99.5775 reason=TARGET         gross_R=+3.4991 confluence=2 rr=3.499
  TSTE  entry=96.1226 stop=95.1352 target=99.5775 exit=98.0000 reason=END_OF_SESSION gross_R=+1.9014 confluence=2 rr=3.499
VERIFY: PASS
```

- 2 winners (TSTW, TSTE), 1 loser (TSTL); `win_rate = 2/3`.
- Equity-curve exit order: TSTL (STOP, ~10:52) → TSTW (TARGET, ~10:53) →
  TSTE (END_OF_SESSION, 15:50). Cumulative net R: `[-1.0, +2.50, +4.40]` —
  `cumulative[0] < 0`, `cumulative[-1] > 0`, `cumulative[-1] == max`.
- `max_drawdown_r = -1.0` (the single STOP is the only drawdown episode);
  `average_loss_r = -1.0`; `profit_factor` finite and > 0.
- TSTE's END_OF_SESSION exit is `+1.90R` gross — still a net winner at the
  worst DEFAULT cost scenario (20 bps ≈ 0.4R), so the trade-count and
  win/loss mix are cost-invariant while `total_r` / expectancy strictly
  worsen as cost rises.

## Reproducibility

`python scripts/gen_sample_multi_trade_1m.py` rewrites the CSV byte-for-byte
from `sample_AAPL_trade_1m.csv` + fixed constants. No result ledger is
hand-edited. Row counts: TSTW 3986, TSTL 3987, TSTE 4286 (12 260 total),
span `2025-12-23 09:30` → `2026-01-06 15:55`.
